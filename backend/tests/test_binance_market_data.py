from decimal import Decimal

import httpx
import pytest

from app.integrations.market_data.binance import BinanceCryptoPriceProvider


@pytest.mark.asyncio
async def test_ldusdc_uses_underlying_usdc_market_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "USDCEUR",
                            "status": "TRADING",
                            "baseAsset": "USDC",
                            "quoteAsset": "EUR",
                        }
                    ]
                },
            )
        return httpx.Response(200, json=[{"symbol": "USDCEUR", "price": "0.92"}])

    provider = BinanceCryptoPriceProvider(httpx.MockTransport(handler))

    assert await provider.rates_to_eur({"LDUSDC"}) == {
        "LDUSDC": Decimal("0.92")
    }
