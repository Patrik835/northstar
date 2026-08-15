import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument, InstrumentAlias
from app.models.market_data import FxRate, HistoricalPrice
from app.models.portfolio import (
    HoldingMetadata,
    PortfolioSnapshot,
    Position,
    Transaction,
)


@dataclass(frozen=True, slots=True)
class HoldingPositionRow:
    position: Position
    broker: Broker
    connection_id: uuid.UUID
    last_synced_at: datetime | None
    instrument: Instrument | None
    reconciliation_difference_percent: Decimal | None = None
    reconciliation_checked_at: datetime | None = None
    reconciliation_warning: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionQualityRow:
    broker: Broker
    connection_id: uuid.UUID
    reconciliation_difference_percent: Decimal | None
    reconciliation_checked_at: datetime | None
    reconciliation_warning: str | None


@dataclass(frozen=True, slots=True)
class TransactionRow:
    transaction: Transaction
    broker: Broker
    connection_id: uuid.UUID
    instrument: Instrument | None


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    snapshot: PortfolioSnapshot
    broker: Broker
    connection_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class HistoricalPriceRow:
    price: HistoricalPrice
    instrument: Instrument


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
                reconciliation_difference_percent=(
                    connection.reconciliation_difference_percent
                ),
                reconciliation_checked_at=connection.reconciliation_checked_at,
                reconciliation_warning=connection.reconciliation_warning,
            )
            for position, connection, instrument in rows
        ]

    async def connection_quality(self, user_id: uuid.UUID) -> list[ConnectionQualityRow]:
        rows = await self.db.execute(
            select(BrokerConnection).where(BrokerConnection.user_id == user_id)
        )
        return [
            ConnectionQualityRow(
                broker=connection.broker,
                connection_id=connection.id,
                reconciliation_difference_percent=(
                    connection.reconciliation_difference_percent
                ),
                reconciliation_checked_at=connection.reconciliation_checked_at,
                reconciliation_warning=connection.reconciliation_warning,
            )
            for connection in rows.scalars()
        ]

    async def transaction_rows(self, user_id: uuid.UUID) -> list[TransactionRow]:
        rows = list(
            (
                await self.db.execute(
                    select(Transaction, BrokerConnection)
                    .join(
                        BrokerConnection,
                        Transaction.broker_connection_id == BrokerConnection.id,
                    )
                    .where(BrokerConnection.user_id == user_id)
                    .order_by(Transaction.executed_at.asc())
                )
            ).all()
        )
        aliases = list(
            (
                await self.db.execute(
                    select(InstrumentAlias, Instrument)
                    .join(Instrument, InstrumentAlias.instrument_id == Instrument.id)
                )
            ).all()
        )
        alias_map = {
            (alias.broker, alias.provider_symbol.casefold()): instrument
            for alias, instrument in aliases
        }
        return [
            TransactionRow(
                transaction=transaction,
                broker=connection.broker,
                connection_id=connection.id,
                instrument=alias_map.get(
                    (connection.broker, transaction.ticker.casefold())
                ),
            )
            for transaction, connection in rows
        ]

    async def snapshot_rows(self, user_id: uuid.UUID) -> list[SnapshotRow]:
        rows = await self.db.execute(
            select(PortfolioSnapshot, BrokerConnection)
            .join(
                BrokerConnection,
                PortfolioSnapshot.broker_connection_id == BrokerConnection.id,
            )
            .where(BrokerConnection.user_id == user_id)
            .order_by(PortfolioSnapshot.snapshot_date.asc())
        )
        return [
            SnapshotRow(
                snapshot=snapshot,
                broker=connection.broker,
                connection_id=connection.id,
            )
            for snapshot, connection in rows
        ]

    async def historical_price_rows(
        self, user_id: uuid.UUID, start_date: date | None, end_date: date
    ) -> list[HistoricalPriceRow]:
        instrument_ids = (
            select(Position.canonical_instrument_id)
            .join(BrokerConnection)
            .where(
                BrokerConnection.user_id == user_id,
                Position.canonical_instrument_id.is_not(None),
            )
        )
        query = (
            select(HistoricalPrice, Instrument)
            .join(Instrument, HistoricalPrice.instrument_id == Instrument.id)
            .where(
                HistoricalPrice.instrument_id.in_(instrument_ids),
                HistoricalPrice.price_date <= end_date,
            )
            .order_by(HistoricalPrice.price_date.asc())
        )
        if start_date is not None:
            query = query.where(HistoricalPrice.price_date >= start_date - timedelta(days=14))
        rows = await self.db.execute(query)
        return [
            HistoricalPriceRow(price=price, instrument=instrument)
            for price, instrument in rows
        ]

    async def historical_usd_eur_rates(
        self, start_date: date | None, end_date: date
    ) -> list[FxRate]:
        query = select(FxRate).where(
            FxRate.source == "ALPHA_VANTAGE",
            FxRate.base_currency == "USD",
            FxRate.quote_currency == "EUR",
            FxRate.rate_date <= end_date,
        )
        if start_date is not None:
            query = query.where(FxRate.rate_date >= start_date - timedelta(days=14))
        return list(await self.db.scalars(query.order_by(FxRate.rate_date.asc())))

    async def holding_metadata(self, user_id: uuid.UUID) -> dict[str, HoldingMetadata]:
        rows = await self.db.scalars(
            select(HoldingMetadata).where(HoldingMetadata.user_id == user_id)
        )
        return {row.holding_key: row for row in rows}

    async def get_holding_metadata(
        self, user_id: uuid.UUID, holding_key: str
    ) -> HoldingMetadata | None:
        return await self.db.scalar(
            select(HoldingMetadata).where(
                HoldingMetadata.user_id == user_id,
                HoldingMetadata.holding_key == holding_key,
            )
        )

    async def save_holding_metadata(self, metadata: HoldingMetadata) -> HoldingMetadata:
        self.db.add(metadata)
        await self.db.commit()
        await self.db.refresh(metadata)
        return metadata
