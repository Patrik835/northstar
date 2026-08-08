from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.integrations.market_data import EcbFxRateProvider, FxRateError
from app.models.market_data import FxRate


def _transport() -> httpx.MockTransport:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <Envelope><Cube><Cube time="2026-08-06">
      <Cube currency="USD" rate="1.2000"/>
      <Cube currency="GBP" rate="0.8000"/>
    </Cube></Cube></Envelope>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=xml, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ecb_converts_reference_currency_to_eur() -> None:
    provider = EcbFxRateProvider(transport=_transport())

    assert await provider.convert_to_eur(Decimal("120"), "USD") == Decimal("100")
    assert await provider.convert_to_eur(Decimal("10"), "EUR") == Decimal("10")


@pytest.mark.asyncio
async def test_ecb_rejects_unsupported_currency() -> None:
    provider = EcbFxRateProvider(transport=_transport())

    with pytest.raises(FxRateError, match="does not publish"):
        await provider.convert_to_eur(Decimal("1"), "XYZ")


@pytest.mark.asyncio
async def test_ecb_persists_and_reuses_daily_rates_for_cross_conversion() -> None:
    db = FxSession()
    provider = EcbFxRateProvider(db, transport=_transport())  # type: ignore[arg-type]
    assert await provider.convert(Decimal("120"), "USD", "GBP") == Decimal("80")
    assert {rate.quote_currency for rate in db.added} == {"USD", "GBP"}
    assert {rate.rate_date for rate in db.added} == {date(2026, 8, 6)}

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Stored daily rates should be reused, not {request.url}")

    cached_db = FxSession(db.added, fetched_at=datetime.now(timezone.utc))
    cached_provider = EcbFxRateProvider(  # type: ignore[arg-type]
        cached_db, transport=httpx.MockTransport(no_network)
    )
    assert await cached_provider.convert_to_eur(Decimal("12"), "USD") == Decimal("10")


class FxSession:
    def __init__(
        self,
        rows: list[FxRate] | None = None,
        *,
        fetched_at: datetime | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.added: list[FxRate] = []
        self.fetched_at = fetched_at

    async def scalar(self, statement: Any) -> datetime | date | None:
        sql = str(statement)
        if "max(fx_rates.fetched_at)" in sql:
            return self.fetched_at
        if "max(fx_rates.rate_date)" in sql:
            return max((row.rate_date for row in self.rows), default=None)
        raise AssertionError(f"Unexpected scalar query: {sql}")

    async def scalars(self, statement: Any) -> list[FxRate]:
        return self.rows

    def add(self, rate: FxRate) -> None:
        self.added.append(rate)

    async def flush(self) -> None:
        return None
