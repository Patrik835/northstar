from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.models.enums import Broker

LIVE_BROKERS = frozenset({Broker.TRADING212, Broker.ETORO, Broker.BINANCE})
LIVE_STALE_AFTER = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class FreshnessDetails:
    status: Literal["never_synced", "fresh", "stale"]
    is_stale: bool
    stale_after: datetime | None


def connection_freshness(
    broker: Broker,
    successful_at: datetime | None,
    sync_interval_minutes: int,
    *,
    now: datetime | None = None,
) -> FreshnessDetails:
    stale_after = (
        successful_at + LIVE_STALE_AFTER
        if successful_at is not None and broker in LIVE_BROKERS
        else None
    )
    if successful_at is None:
        status: Literal["never_synced", "fresh", "stale"] = "never_synced"
    elif stale_after is not None and (now or datetime.now(timezone.utc)) > stale_after:
        status = "stale"
    else:
        status = "fresh"
    return FreshnessDetails(status, status != "fresh", stale_after)
