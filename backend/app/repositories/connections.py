import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus
from app.models.sync import SyncRun


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

    async def by_broker(
        self, user_id: uuid.UUID, broker: Broker
    ) -> BrokerConnection | None:
        return await self.db.scalar(
            select(BrokerConnection).where(
                BrokerConnection.user_id == user_id,
                BrokerConnection.broker == broker,
            )
        )

    async def syncable_live(self) -> list[BrokerConnection]:
        result = await self.db.scalars(
            select(BrokerConnection).where(
                BrokerConnection.broker.in_((Broker.TRADING212, Broker.BINANCE, Broker.ETORO)),
                BrokerConnection.status != ConnectionStatus.DISABLED,
            )
        )
        return list(result)

    async def syncable_etoro(self) -> list[BrokerConnection]:
        result = await self.db.scalars(
            select(BrokerConnection).where(
                BrokerConnection.broker == Broker.ETORO,
                BrokerConnection.status != ConnectionStatus.DISABLED,
            )
        )
        return list(result)

    async def sync_runs(
        self, connection_id: uuid.UUID, *, limit: int = 20
    ) -> list[SyncRun]:
        result = await self.db.scalars(
            select(SyncRun)
            .where(SyncRun.broker_connection_id == connection_id)
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
        )
        return list(result)
