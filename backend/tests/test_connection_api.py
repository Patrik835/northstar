import uuid
from typing import Any

import pytest

from app.api.v1 import connections as connections_api
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncTrigger
from app.models.user import User


def _connection(
    user_id: uuid.UUID,
    broker: Broker,
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
) -> BrokerConnection:
    return BrokerConnection(
        id=uuid.uuid4(),
        user_id=user_id,
        broker=broker,
        encrypted_credentials=b"encrypted",
        credential_hint="••••test",
        status=status,
        last_error=None,
        last_synced_at=None,
        last_sync_attempt_at=None,
        last_successful_sync_at=None,
    )


@pytest.mark.asyncio
async def test_sync_all_only_synchronizes_enabled_api_connections(monkeypatch: Any) -> None:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="portfolio-owner",
        password_hash="unused",
        is_admin=False,
        is_active=True,
    )
    connections = [
        _connection(user_id, Broker.TRADING212),
        _connection(user_id, Broker.TRADING212_CRYPTO),
        _connection(user_id, Broker.BINANCE, ConnectionStatus.DISABLED),
        _connection(user_id, Broker.ETORO),
    ]
    synchronized: list[tuple[Broker, SyncTrigger]] = []

    class FakeRepository:
        def __init__(self, db: Any) -> None:
            pass

        async def for_user(self, requested_user_id: uuid.UUID) -> list[BrokerConnection]:
            assert requested_user_id == user_id
            return connections

    class FakeSyncService:
        def __init__(self, db: Any, cipher: Any) -> None:
            pass

        async def sync(
            self, connection: BrokerConnection, *, trigger: SyncTrigger
        ) -> BrokerConnection:
            synchronized.append((connection.broker, trigger))
            return connection

    monkeypatch.setattr(connections_api, "ConnectionRepository", FakeRepository)
    monkeypatch.setattr(connections_api, "ConnectionSyncService", FakeSyncService)

    result = await connections_api.sync_all_connections(user, object())  # type: ignore[arg-type]

    assert synchronized == [
        (Broker.TRADING212, SyncTrigger.MANUAL),
        (Broker.ETORO, SyncTrigger.MANUAL),
    ]
    assert [connection.broker for connection in result] == [
        Broker.TRADING212,
        Broker.ETORO,
    ]
