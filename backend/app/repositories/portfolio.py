import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument
from app.models.portfolio import Position


@dataclass(frozen=True, slots=True)
class HoldingPositionRow:
    position: Position
    broker: Broker
    connection_id: uuid.UUID
    last_synced_at: datetime | None
    instrument: Instrument | None


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
        canonical_type = func.coalesce(Instrument.asset_type, Position.asset_type)
        rows = await self.db.execute(
            select(canonical_type, func.sum(Position.current_value_eur))
            .join(BrokerConnection)
            .outerjoin(Instrument, Position.canonical_instrument_id == Instrument.id)
            .where(BrokerConnection.user_id == user_id)
            .group_by(canonical_type)
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

    async def holding_positions(self, user_id: uuid.UUID) -> list[HoldingPositionRow]:
        rows = await self.db.execute(
            select(Position, BrokerConnection, Instrument)
            .join(BrokerConnection, Position.broker_connection_id == BrokerConnection.id)
            .outerjoin(Instrument, Position.canonical_instrument_id == Instrument.id)
            .where(BrokerConnection.user_id == user_id)
            .order_by(Position.current_value_eur.desc())
        )
        return [
            HoldingPositionRow(
                position=position,
                broker=connection.broker,
                connection_id=connection.id,
                last_synced_at=connection.last_synced_at,
                instrument=instrument,
            )
            for position, connection, instrument in rows
        ]
