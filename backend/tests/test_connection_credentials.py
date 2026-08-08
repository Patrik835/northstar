import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.registry import ConnectorRegistry
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncTrigger
from app.services.connection_sync import ConnectionSyncService
from app.services.connections import ConnectionService, InvalidConnectionCredentials

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def _connection(cipher: CredentialCipher) -> BrokerConnection:
    return BrokerConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        broker=Broker.BINANCE,
        encrypted_credentials=cipher.encrypt(
            {"api_key": "old-public-key", "secret_key": "old-secret-key"}
        ),
        credential_hint="••••-key",
        status=ConnectionStatus.ERROR,
        last_error="Old credentials were rejected.",
    )


@pytest.mark.asyncio
async def test_reconnect_validates_before_replacing_encrypted_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = CredentialCipher(TEST_KEY)
    connection = _connection(cipher)
    db = AsyncMock()
    service = ConnectionService(db, cipher)
    service.repo.owned = AsyncMock(return_value=connection)
    connector = AsyncMock()
    monkeypatch.setattr(
        ConnectorRegistry,
        "create",
        lambda _registry, _broker, _credentials: connector,
    )
    sync = AsyncMock(return_value=connection)
    monkeypatch.setattr(ConnectionSyncService, "sync", sync)
    replacement = {
        "api_key": "new-public-key-1234",
        "secret_key": "new-secret-key-5678",
    }

    result = await service.replace_credentials(
        connection.id, connection.user_id, replacement
    )

    assert result is connection
    connector.validate_credentials.assert_awaited_once_with()
    assert cipher.decrypt(connection.encrypted_credentials) == replacement
    assert b"new-secret-key-5678" not in connection.encrypted_credentials
    assert connection.credential_hint == "••••1234"
    assert connection.status == ConnectionStatus.PENDING
    assert connection.last_error is None
    db.commit.assert_awaited_once_with()
    sync.assert_awaited_once_with(
        connection, connector, trigger=SyncTrigger.MANUAL
    )


@pytest.mark.asyncio
async def test_reconnect_keeps_saved_credentials_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = CredentialCipher(TEST_KEY)
    connection = _connection(cipher)
    original_encrypted = connection.encrypted_credentials
    db = AsyncMock()
    service = ConnectionService(db, cipher)
    service.repo.owned = AsyncMock(return_value=connection)
    connector = AsyncMock()
    connector.validate_credentials.side_effect = InvalidBrokerCredentials(
        "Binance rejected the supplied credentials."
    )
    monkeypatch.setattr(
        ConnectorRegistry,
        "create",
        lambda _registry, _broker, _credentials: connector,
    )

    with pytest.raises(InvalidConnectionCredentials):
        await service.replace_credentials(
            connection.id,
            connection.user_id,
            {"api_key": "invalid-key", "secret_key": "invalid-secret"},
        )

    assert connection.encrypted_credentials == original_encrypted
    assert connection.status == ConnectionStatus.ERROR
    assert connection.last_error == "Old credentials were rejected."
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnect_cannot_access_another_users_connection() -> None:
    cipher = CredentialCipher(TEST_KEY)
    db = AsyncMock()
    service = ConnectionService(db, cipher)
    service.repo.owned = AsyncMock(return_value=None)

    result = await service.replace_credentials(
        uuid.uuid4(),
        uuid.uuid4(),
        {"api_key": "new-key", "secret_key": "new-secret"},
    )

    assert result is None
    db.commit.assert_not_awaited()
