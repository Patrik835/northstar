from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services.operations import backup_status


def test_backup_status_reports_current_stale_and_missing_files(tmp_path) -> None:
    status_file = tmp_path / "latest-success"
    settings = get_settings().model_copy(
        update={"backup_status_file": str(status_file), "backup_max_age_hours": 30}
    )

    assert backup_status(settings)["status"] == "missing"

    status_file.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    assert backup_status(settings)["status"] == "ok"

    status_file.write_text(
        (datetime.now(timezone.utc) - timedelta(hours=31)).isoformat(),
        encoding="utf-8",
    )
    assert backup_status(settings)["status"] == "stale"
