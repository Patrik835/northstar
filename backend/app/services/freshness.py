from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.integrations.connectors.registry import ConnectorRegistry
from app.models.enums import Broker

LIVE_BROKERS = frozenset(ConnectorRegistry().brokers())
LIVE_STALE_AFTER = {
    definition.broker: timedelta(hours=definition.stale_after_hours)
    for definition in ConnectorRegistry().definitions()
}


@dataclass(frozen=True, slots=True)
class FreshnessDetails:
    status: Literal["never_synced", "fresh", "stale"]
    is_stale: bool
    stale_after: datetime | None


def connection_freshness(
    broker: Broker,
    successful_at: datetime | None,
    *,
    now: datetime | None = None,
) -> FreshnessDetails:
    stale_after = (
        successful_at + LIVE_STALE_AFTER[broker]
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
