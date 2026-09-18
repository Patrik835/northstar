import hmac

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import text

from app.api.dependencies import AppSettings, DbSession
from app.services.operations import prometheus_metrics

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(db: DbSession) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database is unavailable"
        ) from exc
    return {"status": "ready"}


@router.get("/metrics", include_in_schema=False)
async def metrics(
    db: DbSession,
    settings: AppSettings,
    authorization: str | None = Header(default=None),
) -> Response:
    expected = settings.monitoring_token
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return Response(
        await prometheus_metrics(db, settings),
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
