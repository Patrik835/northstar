from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app.integrations.market_data.current_prices import CurrentPriceError, CurrentPriceProvider
from app.models.enums import AssetType


@pytest.mark.asyncio
async def test_equity_quote_preserves_currency_and_market_timestamp():
    def respond(request):
        assert request.url.path.endswith("/AAPL")
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 123.5,
                                "currency": "USD",
                                "regularMarketTime": 1770000000,
                            }
                        }
                    ]
                }
            },
        )

    provider = CurrentPriceProvider(httpx.MockTransport(respond))
    assert await provider.price("AAPL", AssetType.STOCK) == (
        Decimal("123.5"),
        "USD",
        datetime.fromtimestamp(1770000000, timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "-1"])
async def test_invalid_market_price_is_rejected(price):
    provider = CurrentPriceProvider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "regularMarketPrice": price,
                                    "currency": "USD",
                                    "regularMarketTime": 1770000000,
                                }
                            }
                        ]
                    }
                },
            )
        )
    )
    with pytest.raises(CurrentPriceError):
        await provider.price("AAPL", AssetType.STOCK)


@pytest.mark.asyncio
async def test_crypto_quote_uses_eur_conversion():
    def respond(request):
        if request.url.path.endswith("exchangeInfo"):
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "BTCEUR",
                            "baseAsset": "BTC",
                            "quoteAsset": "EUR",
                            "status": "TRADING",
                        }
                    ]
                },
            )
        return httpx.Response(200, json=[{"symbol": "BTCEUR", "price": "60000"}])

    provider = CurrentPriceProvider(httpx.MockTransport(respond))
    price, currency, timestamp = await provider.price("BTC", AssetType.CRYPTO)
    assert (price, currency) == (Decimal("60000"), "EUR")
    assert timestamp.tzinfo == timezone.utc
