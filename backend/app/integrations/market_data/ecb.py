from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol
from xml.etree import ElementTree

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import FxRate


class FxRateError(RuntimeError):
    """Raised when a value cannot be converted safely."""


class FxRateProvider(Protocol):
    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of: date | None = None
    ) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class EcbRateSet:
    rate_date: date
    rates: dict[str, Decimal]


class EcbFxRateProvider:
    """Fetch, persist, cache, and apply ECB rates quoted against EUR.

    Database writes are flushed into the caller's transaction; the caller owns commits.
    If today's ECB request fails, the newest stored working-day rates are used.
    """

    source = "ECB"
    base_currency = "EUR"
    rates_url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def __init__(
        self,
        db: AsyncSession | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.db = db
        self._transport = transport
        self._cache: dict[date, dict[str, Decimal]] = {}
        self._checked_on: date | None = None

    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of: date | None = None
    ) -> Decimal:
        return await self.convert(value, currency, "EUR", as_of)

    async def convert(
        self,
        value: Decimal,
        from_currency: str,
        to_currency: str,
        as_of: date | None = None,
    ) -> Decimal:
        source_currency = _normalize_currency(from_currency)
        target_currency = _normalize_currency(to_currency)
        if source_currency == target_currency:
            return value

        rates = await self._rates_for(as_of)
        source_rate = rates.get(source_currency)
        target_rate = rates.get(target_currency)
        if source_rate is None:
            raise FxRateError(
                f"ECB does not publish an EUR reference rate for {source_currency}."
            )
        if target_rate is None:
            raise FxRateError(
                f"ECB does not publish an EUR reference rate for {target_currency}."
            )
        value_in_eur = value / source_rate
        return value_in_eur * target_rate

    async def refresh(self, *, force: bool = False) -> date:
        """Ensure the latest rate set is stored and return its ECB publication date."""

        today = datetime.now(timezone.utc).date()
        if not force and self._checked_on == today and self._cache:
            return max(self._cache)

        if self.db is not None and not force and await self._database_checked_today(today):
            stored = await self._load_stored_rates(today)
            if stored is not None:
                self._remember(stored, today)
                return stored.rate_date

        try:
            fetched = await self._fetch_daily_rates()
        except FxRateError:
            if self.db is not None:
                stored = await self._load_stored_rates(today)
                if stored is not None:
                    self._remember(stored, today)
                    return stored.rate_date
            raise

        if self.db is not None:
            await self._store(fetched)
        self._remember(fetched, today)
        return fetched.rate_date

    async def _rates_for(self, as_of: date | None) -> dict[str, Decimal]:
        today = datetime.now(timezone.utc).date()
        target_date = as_of or today

        cached_dates = [item for item in self._cache if item <= target_date]
        if cached_dates and (as_of is not None or self._checked_on == today):
            return self._cache[max(cached_dates)]

        if as_of is not None and self.db is not None:
            stored = await self._load_stored_rates(target_date)
            if stored is not None:
                self._remember(stored, today)
                return stored.rates

        await self.refresh()
        cached_dates = [item for item in self._cache if item <= target_date]
        if cached_dates:
            return self._cache[max(cached_dates)]
        raise FxRateError(f"No ECB exchange rates are stored for {target_date.isoformat()}.")

    async def _fetch_daily_rates(self) -> EcbRateSet:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0), transport=self._transport
            ) as client:
                response = await client.get(self.rates_url)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            raise FxRateError("ECB exchange rates are temporarily unavailable.") from exc

        rate_date: date | None = None
        rates = {"EUR": Decimal(1)}
        try:
            for element in root.iter():
                if raw_date := element.attrib.get("time"):
                    rate_date = date.fromisoformat(raw_date)
                currency = element.attrib.get("currency")
                raw_rate = element.attrib.get("rate")
                if currency and raw_rate:
                    normalized = _normalize_currency(currency)
                    rate = Decimal(raw_rate)
                    if rate <= 0:
                        raise ValueError("non-positive rate")
                    rates[normalized] = rate
        except (InvalidOperation, ValueError) as exc:
            raise FxRateError("ECB returned invalid exchange-rate data.") from exc

        if rate_date is None or len(rates) == 1:
            raise FxRateError("ECB returned no exchange rates.")
        return EcbRateSet(rate_date=rate_date, rates=rates)

    async def _database_checked_today(self, today: date) -> bool:
        assert self.db is not None
        last_fetch = await self.db.scalar(
            select(func.max(FxRate.fetched_at)).where(FxRate.source == self.source)
        )
        return last_fetch is not None and last_fetch.date() >= today

    async def _load_stored_rates(self, as_of: date) -> EcbRateSet | None:
        assert self.db is not None
        rate_date = await self.db.scalar(
            select(func.max(FxRate.rate_date)).where(
                FxRate.source == self.source,
                FxRate.base_currency == self.base_currency,
                FxRate.rate_date <= as_of,
            )
        )
        if rate_date is None:
            return None
        rows = list(
            await self.db.scalars(
                select(FxRate).where(
                    FxRate.source == self.source,
                    FxRate.base_currency == self.base_currency,
                    FxRate.rate_date == rate_date,
                )
            )
        )
        rates = {"EUR": Decimal(1)}
        rates.update({row.quote_currency: row.rate for row in rows})
        return EcbRateSet(rate_date=rate_date, rates=rates)

    async def _store(self, rate_set: EcbRateSet) -> None:
        assert self.db is not None
        existing = {
            row.quote_currency: row
            for row in await self.db.scalars(
                select(FxRate).where(
                    FxRate.source == self.source,
                    FxRate.base_currency == self.base_currency,
                    FxRate.rate_date == rate_set.rate_date,
                )
            )
        }
        fetched_at = datetime.now(timezone.utc)
        for currency, rate in rate_set.rates.items():
            if currency == self.base_currency:
                continue
            if stored := existing.get(currency):
                stored.rate = rate
                stored.fetched_at = fetched_at
            else:
                self.db.add(
                    FxRate(
                        source=self.source,
                        rate_date=rate_set.rate_date,
                        base_currency=self.base_currency,
                        quote_currency=currency,
                        rate=rate,
                        fetched_at=fetched_at,
                    )
                )
        await self.db.flush()

    def _remember(self, rate_set: EcbRateSet, checked_on: date) -> None:
        self._cache[rate_set.rate_date] = rate_set.rates
        self._checked_on = checked_on


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise FxRateError("Currency codes must contain exactly three letters.")
    return normalized
