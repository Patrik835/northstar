import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.database import SessionFactory
from app.models.operations import OperationalJobRun
from app.models.sync import SyncRun

logger = logging.getLogger(__name__)


async def run_monitored_job(
    job_name: str, job: Callable[[], Awaitable[None]]
) -> None:
    started = datetime.now(timezone.utc)
    async with SessionFactory() as db:
        run = OperationalJobRun(job_name=job_name, status="running", started_at=started)
        db.add(run)
        await db.commit()
        run_id = run.id
    try:
        await job()
    except Exception as exc:
        logger.exception("Scheduled job failed", extra={"job_name": job_name})
        async with SessionFactory() as db:
            run = await db.get(OperationalJobRun, run_id)
            if run:
                finished = datetime.now(timezone.utc)
                run.status = "error"
                run.safe_detail = f"{type(exc).__name__}: scheduled job failed"
                run.finished_at = finished
                run.duration_ms = int((finished - started).total_seconds() * 1000)
                await db.commit()
        raise
    else:
        async with SessionFactory() as db:
            run = await db.get(OperationalJobRun, run_id)
            if run:
                finished = datetime.now(timezone.utc)
                run.status = "success"
                run.finished_at = finished
                run.duration_ms = int((finished - started).total_seconds() * 1000)
                await db.commit()


def monitored_job(
    name: str, job: Callable[[], Awaitable[None]]
) -> Callable[[], Awaitable[None]]:
    async def execute() -> None:
        await run_monitored_job(name, job)

    execute.__name__ = f"monitored_{name.replace('-', '_')}"
    return execute


def backup_status(settings: Settings) -> dict[str, Any]:
    path = Path(settings.backup_status_file)
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        value = path.read_text(encoding="utf-8").strip()
        if value:
            modified = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OSError, ValueError):
        return {"status": "missing", "last_success_at": None, "age_seconds": None}
    age = max(0, int((datetime.now(timezone.utc) - modified).total_seconds()))
    maximum = settings.backup_max_age_hours * 3600
    return {
        "status": "ok" if age <= maximum else "stale",
        "last_success_at": modified,
        "age_seconds": age,
    }


async def operations_snapshot(db: Any, settings: Settings) -> dict[str, Any]:
    jobs = list(
        await db.scalars(
            select(OperationalJobRun)
            .order_by(OperationalJobRun.started_at.desc())
            .limit(30)
        )
    )
    sync_failures = list(
        await db.scalars(
            select(SyncRun)
            .where(SyncRun.status.in_(["error", "partial"]))
            .order_by(SyncRun.started_at.desc())
            .limit(20)
        )
    )
    return {
        "backup": backup_status(settings),
        "jobs": [
            {
                "id": item.id,
                "job_name": item.job_name,
                "status": item.status,
                "safe_detail": item.safe_detail,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
                "duration_ms": item.duration_ms,
            }
            for item in jobs
        ],
        "sync_failures": [
            {
                "id": item.id,
                "connection_id": item.broker_connection_id,
                "status": item.status,
                "safe_detail": item.safe_error_detail,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            for item in sync_failures
        ],
    }


async def prometheus_metrics(db: Any, settings: Settings) -> str:
    job_counts = list(
        await db.execute(
            select(OperationalJobRun.status, func.count()).group_by(OperationalJobRun.status)
        )
    )
    sync_counts = list(
        await db.execute(select(SyncRun.status, func.count()).group_by(SyncRun.status))
    )
    backup = backup_status(settings)
    lines = [
        "# HELP northstar_up Whether the API process is serving requests.",
        "# TYPE northstar_up gauge",
        "northstar_up 1",
        "# HELP northstar_job_runs_total Persisted scheduled job runs by status.",
        "# TYPE northstar_job_runs_total gauge",
    ]
    lines.extend(
        f'northstar_job_runs_total{{status="{status}"}} {count}'
        for status, count in job_counts
    )
    lines.extend(
        [
            "# HELP northstar_sync_runs_total Persisted connector sync runs by status.",
            "# TYPE northstar_sync_runs_total gauge",
        ]
    )
    lines.extend(
        f'northstar_sync_runs_total{{status="{getattr(status, "value", status)}"}} {count}'
        for status, count in sync_counts
    )
    lines.extend(
        [
            "# HELP northstar_backup_age_seconds Age of the last verified PostgreSQL backup.",
            "# TYPE northstar_backup_age_seconds gauge",
            "northstar_backup_age_seconds "
            f'{backup["age_seconds"] if backup["age_seconds"] is not None else -1}',
        ]
    )
    return "\n".join(lines) + "\n"
