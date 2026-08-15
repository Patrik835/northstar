import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.market_data.alpha_vantage import (
    AlphaVantageProvider,
    AlphaVantageRateLimitError,
)


@pytest.mark.asyncio
async def test_alpha_vantage_parses_weekly_equity_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["function"] == "TIME_SERIES_WEEKLY"
        assert request.url.params["symbol"] == "MSFT"
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "Weekly Time Series": {
                        "2026-08-14": {"4. close": "420.25"},
                        "2026-08-07": {"4. close": "410.10"},
                    }
                }
            ).encode(),
        )

    provider = AlphaVantageProvider("secret", httpx.MockTransport(handler))
    points = await provider.weekly_equity("MSFT")

    assert points[0].price_date == date(2026, 8, 7)
    assert points[-1].close == Decimal("420.25")


@pytest.mark.asyncio
async def test_alpha_vantage_surfaces_provider_limit_safely() -> None:
    provider = AlphaVantageProvider(
        "secret",
        httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"Information": "Daily limit reached"})
        ),
    )

    with pytest.raises(AlphaVantageRateLimitError, match="Daily limit reached"):
        await provider.weekly_equity("MSFT")


@pytest.mark.asyncio
async def test_alpha_vantage_parses_company_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["function"] == "OVERVIEW"
        return httpx.Response(
            200,
            json={"Sector": "Technology", "Industry": "Software", "Country": "USA"},
        )

    provider = AlphaVantageProvider("secret", httpx.MockTransport(handler))
    overview = await provider.company_overview("MSFT")

    assert overview.sector == "Technology"
    assert overview.country == "USA"
