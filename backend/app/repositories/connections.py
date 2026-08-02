import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus


class ConnectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_user(self, user_id: uuid.UUID) -> list[BrokerConnection]:
        result = await self.db.scalars(
            select(BrokerConnection)
            .where(BrokerConnection.user_id == user_id)
            .order_by(BrokerConnection.created_at)
        )
        return list(result)

    async def owned(self, connection_id: uuid.UUID, user_id: uuid.UUID) -> BrokerConnection | None:
        return await self.db.scalar(
            select(BrokerConnection).where(
                BrokerConnection.id == connection_id, BrokerConnection.user_id == user_id
            )
        )

    async def syncable_live(self) -> list[BrokerConnection]:
        result = await self.db.scalars(
            select(BrokerConnection).where(
                BrokerConnection.broker == Broker.TRADING212,
                BrokerConnection.status != ConnectionStatus.DISABLED,
            )
        )
        return list(result)
