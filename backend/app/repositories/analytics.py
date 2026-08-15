import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AssetType
from app.models.instrument import Instrument
from app.models.market_data import FxRate, HistoricalPrice
from app.models.portfolio import HoldingMetadata, Position
from app.models.user import UserProfile


class AnalyticsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def benchmark_options(self) -> list[Instrument]:
        has_prices = exists().where(HistoricalPrice.instrument_id == Instrument.id)
        return list(
            await self.db.scalars(
                select(Instrument)
                .where(Instrument.asset_type == AssetType.ETF, has_prices)
                .order_by(Instrument.canonical_symbol.asc())
            )
        )

    async def benchmark_prices(
        self, instrument_id: uuid.UUID, start_date: date | None, end_date: date
    ) -> list[HistoricalPrice]:
        query = select(HistoricalPrice).where(
            HistoricalPrice.instrument_id == instrument_id,
            HistoricalPrice.price_date <= end_date,
        )
        if start_date is not None:
            query = query.where(
                HistoricalPrice.price_date >= start_date - timedelta(days=14)
            )
        return list(
            await self.db.scalars(query.order_by(HistoricalPrice.price_date.asc()))
        )

    async def usd_eur_rates(
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

    async def profile(self, user_id: uuid.UUID) -> UserProfile | None:
        return await self.db.get(UserProfile, user_id)

    async def set_benchmark(
        self, user_id: uuid.UUID, instrument_id: uuid.UUID | None
    ) -> None:
        profile = await self.profile(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.db.add(profile)
        profile.benchmark_instrument_id = instrument_id
        await self.db.commit()

    async def save_targets(
        self, user_id: uuid.UUID, values: dict[str, Decimal | None]
    ) -> None:
        existing = {
            row.holding_key: row
            for row in await self.db.scalars(
                select(HoldingMetadata).where(
                    HoldingMetadata.user_id == user_id,
                    HoldingMetadata.holding_key.in_(values),
                )
            )
        }
        for holding_key, target in values.items():
            row = existing.get(holding_key)
            if row is None:
                row = HoldingMetadata(user_id=user_id, holding_key=holding_key)
                self.db.add(row)
            row.target_allocation_percentage = target
        await self.db.commit()

    async def benchmark_instrument(
        self, instrument_id: uuid.UUID
    ) -> Instrument | None:
        return await self.db.scalar(
            select(Instrument).where(
                Instrument.id == instrument_id,
                Instrument.asset_type == AssetType.ETF,
            )
        )

    async def instrument_is_held_by_user(
        self, user_id: uuid.UUID, instrument_id: uuid.UUID
    ) -> bool:
        return bool(
            await self.db.scalar(
                select(exists().where(
                    Position.canonical_instrument_id == instrument_id,
                    Position.connection.has(user_id=user_id),
                ))
            )
        )
