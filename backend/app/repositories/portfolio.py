import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker
from app.models.portfolio import Position


class PortfolioRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def total(self, user_id: uuid.UUID) -> Decimal:
        value = await self.db.scalar(
            select(func.coalesce(func.sum(Position.current_value_eur), 0))
            .join(BrokerConnection)
            .where(BrokerConnection.user_id == user_id)
        )
        return Decimal(value)

    async def by_source(self, user_id: uuid.UUID) -> list[tuple[Broker, Decimal]]:
        rows = await self.db.execute(
            select(BrokerConnection.broker, func.sum(Position.current_value_eur))
            .join(Position)
            .where(BrokerConnection.user_id == user_id)
            .group_by(BrokerConnection.broker)
        )
        return [(broker, Decimal(value)) for broker, value in rows]

    async def by_asset_type(self, user_id: uuid.UUID) -> list[tuple[AssetType, Decimal]]:
        rows = await self.db.execute(
            select(Position.asset_type, func.sum(Position.current_value_eur))
            .join(BrokerConnection)
            .where(BrokerConnection.user_id == user_id)
            .group_by(Position.asset_type)
        )
        return [(asset_type, Decimal(value)) for asset_type, value in rows]

    async def position_count(self, user_id: uuid.UUID) -> int:
        return int(
            await self.db.scalar(
                select(func.count(Position.id))
                .join(BrokerConnection)
                .where(BrokerConnection.user_id == user_id)
            )
            or 0
        )
