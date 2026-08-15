import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_data import (
    AlphaVantageError,
    AlphaVantageProvider,
    AlphaVantageRateLimitError,
)
from app.models.enums import AssetType
from app.models.instrument import Instrument
from app.models.market_data import FxRate, HistoricalPrice
from app.models.portfolio import Position

logger = logging.getLogger(__name__)

SOURCE = "ALPHA_VANTAGE"


def alpha_vantage_symbol(instrument: Instrument) -> tuple[str, str]:
    symbol = instrument.canonical_symbol.upper()
    if symbol == "SPY5.L":
        return "SPY5.LON", "USD"
    if symbol == "FB":
        return "META", "USD"
    if symbol == "DMYI":
        return "IONQ", "USD"
    if symbol == "ASML" and instrument.isin:
        return "ASML.AMS", "EUR"
    return symbol, "USD"


class HistoricalMarketDataService:
    """Fill a durable weekly cache while respecting Alpha Vantage's free allowance."""

    def __init__(
        self,
        db: AsyncSession,
        provider: AlphaVantageProvider,
        daily_request_limit: int = 25,
        request_interval_seconds: float = 1.1,
    ) -> None:
        self.db = db
        self.provider = provider
        self.daily_request_limit = daily_request_limit
        self.request_interval_seconds = request_interval_seconds
        self._last_request_at: float | None = None

    async def refresh(self) -> tuple[int, int]:
        requests_left = self.daily_request_limit
        stored_points = 0
        if not await self._has_recent_usd_fx():
            try:
                await self._wait_for_request_slot()
                stored_points += await self._store_usd_fx()
                requests_left -= 1
            except AlphaVantageError as exc:
                logger.warning("Alpha Vantage USD/EUR history failed: %s", exc)
                return 0, 0

        instruments = await self._prioritized_instruments()
        refreshed = 0
        for instrument in instruments:
            if requests_left <= 0:
                break
            if await self._has_recent_price(instrument.id):
                continue
            symbol, currency = alpha_vantage_symbol(instrument)
            try:
                await self._wait_for_request_slot()
                points = await self.provider.weekly_equity(symbol)
            except AlphaVantageRateLimitError as exc:
                logger.warning("Alpha Vantage rate limit reached; backfill paused: %s", exc)
                return refreshed, stored_points
            except AlphaVantageError as exc:
                logger.warning("Alpha Vantage history failed for %s: %s", symbol, exc)
                requests_left -= 1
                continue
            stored_points += await self._store_prices(instrument, currency, points)
            requests_left -= 1
            refreshed += 1
            await self.db.commit()

        for instrument in instruments:
            if requests_left <= 0:
                break
            if instrument.asset_type is AssetType.ETF:
                continue
            if not self._metadata_needs_refresh(instrument):
                continue
            symbol, _ = alpha_vantage_symbol(instrument)
            try:
                await self._wait_for_request_slot()
                overview = await self.provider.company_overview(symbol)
                instrument.sector = overview.sector
                instrument.industry = overview.industry
                instrument.country = overview.country
                instrument.metadata_source = SOURCE
                instrument.metadata_updated_at = datetime.now(timezone.utc)
                requests_left -= 1
                await self.db.commit()
            except AlphaVantageRateLimitError as exc:
                logger.warning("Alpha Vantage rate limit reached; enrichment paused: %s", exc)
                break
            except AlphaVantageError as exc:
                logger.warning("Alpha Vantage metadata failed for %s: %s", symbol, exc)
                requests_left -= 1
        return refreshed, stored_points

    async def _wait_for_request_slot(self) -> None:
        if self._last_request_at is not None:
            elapsed = monotonic() - self._last_request_at
            if elapsed < self.request_interval_seconds:
                await asyncio.sleep(self.request_interval_seconds - elapsed)
        self._last_request_at = monotonic()

    async def _prioritized_instruments(self) -> list[Instrument]:
        rows = await self.db.execute(
            select(Instrument, func.sum(Position.current_value_eur).label("value"))
            .join(Position, Position.canonical_instrument_id == Instrument.id)
            .where(Instrument.asset_type.in_([AssetType.STOCK, AssetType.ETF]))
            .group_by(Instrument.id)
            .order_by(func.sum(Position.current_value_eur).desc())
        )
        return [instrument for instrument, _ in rows]

    async def _has_recent_price(self, instrument_id: object) -> bool:
        newest = await self.db.scalar(
            select(func.max(HistoricalPrice.price_date)).where(
                HistoricalPrice.instrument_id == instrument_id,
                HistoricalPrice.source == SOURCE,
            )
        )
        return newest is not None and newest >= date.today() - timedelta(days=10)

    async def _has_recent_usd_fx(self) -> bool:
        newest = await self.db.scalar(
            select(func.max(FxRate.rate_date)).where(
                FxRate.source == SOURCE,
                FxRate.base_currency == "USD",
                FxRate.quote_currency == "EUR",
            )
        )
        return newest is not None and newest >= date.today() - timedelta(days=10)

    async def _store_usd_fx(self) -> int:
        points = await self.provider.weekly_fx("USD", "EUR")
        existing_dates = set(
            await self.db.scalars(
                select(FxRate.rate_date).where(
                    FxRate.source == SOURCE,
                    FxRate.base_currency == "USD",
                    FxRate.quote_currency == "EUR",
                )
            )
        )
        for point in points:
            if point.price_date not in existing_dates:
                self.db.add(
                    FxRate(
                        source=SOURCE,
                        rate_date=point.price_date,
                        base_currency="USD",
                        quote_currency="EUR",
                        rate=point.close,
                    )
                )
        await self.db.commit()
        return sum(point.price_date not in existing_dates for point in points)

    async def _store_prices(self, instrument: Instrument, currency: str, points: list) -> int:
        existing_dates = set(
            await self.db.scalars(
                select(HistoricalPrice.price_date).where(
                    HistoricalPrice.instrument_id == instrument.id,
                    HistoricalPrice.source == SOURCE,
                )
            )
        )
        for point in points:
            if point.price_date not in existing_dates:
                self.db.add(
                    HistoricalPrice(
                        instrument_id=instrument.id,
                        price_date=point.price_date,
                        close_price=point.close,
                        currency=currency,
                        source=SOURCE,
                        interval="weekly",
                    )
                )
        return sum(point.price_date not in existing_dates for point in points)

    @staticmethod
    def _metadata_needs_refresh(instrument: Instrument) -> bool:
        updated_at = instrument.metadata_updated_at
        if updated_at is None:
            return True
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return updated_at < datetime.now(timezone.utc) - timedelta(days=90)
