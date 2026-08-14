import uuid
from datetime import datetime, timedelta, timezone

from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus
from app.schemas.connection import ConnectionRead


def _connection(broker: Broker, successful_at: datetime | None) -> BrokerConnection:
    return BrokerConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        broker=broker,
        encrypted_credentials=b"encrypted",
        credential_hint="••••test",
        status=ConnectionStatus.ACTIVE,
        last_successful_sync_at=successful_at,
        last_synced_at=successful_at,
    )


def test_live_connection_becomes_stale_after_24_hours() -> None:
    connection = _connection(
        Broker.TRADING212, datetime.now(timezone.utc) - timedelta(hours=25)
    )

    result = ConnectionRead.from_connection(connection, sync_interval_minutes=120)

    assert result.freshness_status == "stale"
    assert result.is_stale is True
    assert result.stale_after is not None


def test_live_connection_is_fresh_within_24_hours() -> None:
    connection = _connection(
        Broker.TRADING212, datetime.now(timezone.utc) - timedelta(hours=23)
    )

    result = ConnectionRead.from_connection(connection, sync_interval_minutes=120)

    assert result.freshness_status == "fresh"
    assert result.is_stale is False


def test_manual_csv_import_is_not_marked_stale_by_live_sync_schedule() -> None:
    connection = _connection(
        Broker.TRADING212_CRYPTO, datetime.now(timezone.utc) - timedelta(days=30)
    )

    result = ConnectionRead.from_connection(connection, sync_interval_minutes=120)

    assert result.freshness_status == "fresh"
    assert result.is_stale is False
    assert result.stale_after is None


def test_never_synchronized_connection_is_explicit() -> None:
    result = ConnectionRead.from_connection(
        _connection(Broker.BINANCE, None), sync_interval_minutes=120
    )

    assert result.freshness_status == "never_synced"
    assert result.is_stale is True
