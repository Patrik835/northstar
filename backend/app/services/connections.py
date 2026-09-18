import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher, mask_secret
from app.integrations.connectors.base import BrokerConnector, ConnectorError
from app.integrations.connectors.registry import ConnectorRegistry
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncTrigger
from app.repositories.connections import ConnectionRepository
from app.services.connection_sync import ConnectionSyncService


class InvalidConnectionCredentials(ValueError):
    pass


class ConnectionService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        registry: ConnectorRegistry | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.repo = ConnectionRepository(db)
        self.registry = registry or ConnectorRegistry()

    async def create(
        self, user_id: uuid.UUID, broker: Broker, credentials: dict[str, str]
    ) -> BrokerConnection:
        credentials = _normalized_credentials(credentials)
        required, connector = await self._validate(broker, credentials)

        key_hint = mask_secret(credentials[required[0]])
        connection = BrokerConnection(
            user_id=user_id,
            broker=broker,
            encrypted_credentials=self.cipher.encrypt(credentials),
            credential_hint=key_hint,
            status=ConnectionStatus.PENDING,
        )
        self.db.add(connection)
        await self.db.commit()
        await self.db.refresh(connection)
        return await ConnectionSyncService(self.db, self.cipher).sync(
            connection, connector, trigger=SyncTrigger.INITIAL
        )

    async def replace_credentials(
        self,
        connection_id: uuid.UUID,
        user_id: uuid.UUID,
        credentials: dict[str, str],
    ) -> BrokerConnection | None:
        connection = await self.repo.owned(connection_id, user_id)
        if not connection:
            return None

        credentials = _normalized_credentials(credentials)
        required, connector = await self._validate(connection.broker, credentials)
        connection.encrypted_credentials = self.cipher.encrypt(credentials)
        connection.credential_hint = mask_secret(credentials[required[0]])
        connection.status = ConnectionStatus.PENDING
        connection.last_error = None
        await self.db.commit()
        await self.db.refresh(connection)
        return await ConnectionSyncService(self.db, self.cipher).sync(
            connection, connector, trigger=SyncTrigger.MANUAL
        )

    async def delete(self, connection_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        connection = await self.repo.owned(connection_id, user_id)
        if not connection:
            return False
        await self.db.delete(connection)
        await self.db.commit()
        return True

    async def _validate(
        self, broker: Broker, credentials: dict[str, str]
    ) -> tuple[tuple[str, ...], BrokerConnector]:
        try:
            required = self.registry.definition(broker).credential_fields
        except ValueError as exc:
            raise InvalidConnectionCredentials(
                f"{broker.value} is not available as a live connection"
            ) from exc
        if set(credentials) != set(required) or any(not credentials[k] for k in required):
            raise InvalidConnectionCredentials(
                f"Expected exactly these credential fields: {', '.join(required)}"
            )
        connector = self.registry.create(broker, credentials)
        try:
            await connector.validate_credentials()
        except ConnectorError as exc:
            raise InvalidConnectionCredentials(str(exc)) from exc
        return required, connector


def _normalized_credentials(credentials: dict[str, str]) -> dict[str, str]:
    return {key: value.strip() for key, value in credentials.items()}
