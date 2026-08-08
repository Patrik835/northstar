import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Broker, ConnectionStatus, SyncRunStatus, SyncTrigger

if TYPE_CHECKING:
    from app.models.broker import BrokerConnection


class ConnectionCreate(BaseModel):
    broker: Broker
    credentials: dict[str, str] = Field(min_length=1)


class ConnectionCredentialsUpdate(BaseModel):
    credentials: dict[str, str] = Field(min_length=1)


class ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    broker: Broker
    credential_hint: str
    status: ConnectionStatus
    last_error: str | None
    last_synced_at: datetime | None
    last_sync_attempt_at: datetime | None = None
    last_successful_sync_at: datetime | None = None
    freshness_status: Literal["never_synced", "fresh", "stale"] = "never_synced"
    is_stale: bool = True
    stale_after: datetime | None = None

    @classmethod
    def from_connection(
        cls, connection: "BrokerConnection", sync_interval_minutes: int
    ) -> "ConnectionRead":
        successful_at = connection.last_successful_sync_at or connection.last_synced_at
        is_live = connection.broker in {
            Broker.TRADING212,
            Broker.ETORO,
            Broker.BINANCE,
        }
        stale_after = (
            successful_at + timedelta(minutes=sync_interval_minutes * 2)
            if successful_at is not None and is_live
            else None
        )
        if successful_at is None:
            freshness_status: Literal["never_synced", "fresh", "stale"] = "never_synced"
        elif stale_after is not None and datetime.now(timezone.utc) > stale_after:
            freshness_status = "stale"
        else:
            freshness_status = "fresh"
        return cls.model_validate(connection).model_copy(
            update={
                "last_successful_sync_at": successful_at,
                "freshness_status": freshness_status,
                "is_stale": freshness_status != "fresh",
                "stale_after": stale_after,
            }
        )


class ConnectionGuide(BaseModel):
    broker: Broker
    connection_type: Literal["api", "csv"]
    category: str
    description: str
    credential_fields: list[str]
    credential_labels: dict[str, str]
    security_notice: str
    setup_steps: list[str]
    tutorial_url: str


class CryptoCsvImportResult(BaseModel):
    connection: ConnectionRead
    rows_read: int
    transactions_added: int
    duplicates_skipped: int
    positions_imported: int
    warnings: list[str]


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: SyncRunStatus
    trigger: SyncTrigger
    positions_written: int
    transactions_read: int
    transactions_written: int
    warning_count: int
    safe_error_detail: str | None
    started_at: datetime
    finished_at: datetime | None
