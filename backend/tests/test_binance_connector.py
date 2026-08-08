import hashlib
import hmac
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode

import httpx
import pytest

from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.binance import BinanceConnector
from app.models.enums import AssetType, TransactionType


def _transport(invalid_credentials: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_800_000_000_000}, request=request)

        if request.url.path == "/api/v3/account":
            assert request.headers["X-MBX-APIKEY"] == "test-key"
            pairs = parse_qsl(request.url.query.decode())
            supplied_signature = dict(pairs)["signature"]
            unsigned = [(key, value) for key, value in pairs if key != "signature"]
            expected = hmac.new(
                b"test-secret", urlencode(unsigned).encode(), hashlib.sha256
            ).hexdigest()
            assert supplied_signature == expected
            if invalid_credentials:
                return httpx.Response(
                    401, json={"code": -2015, "msg": "Invalid API-key"}, request=request
                )
            return httpx.Response(
                200,
                json={
                    "accountType": "SPOT",
                    "balances": [
                        {"asset": "BTC", "free": "0.1", "locked": "0"},
                        {"asset": "EUR", "free": "100", "locked": "0"},
                    ],
                },
                request=request,
            )

        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "BTCEUR",
                            "status": "TRADING",
                            "baseAsset": "BTC",
                            "quoteAsset": "EUR",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/api/v3/ticker/price":
            return httpx.Response(
                200, json=[{"symbol": "BTCEUR", "price": "50000"}], request=request
            )
        if request.url.path == "/api/v3/myTrades":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "BTCEUR",
                        "id": 42,
                        "price": "40000",
                        "qty": "0.1",
                        "quoteQty": "4000",
                        "commission": "0.0001",
                        "commissionAsset": "BTC",
                        "time": 1_799_000_000_000,
                        "isBuyer": True,
                    }
                ],
                request=request,
            )
        raise AssertionError(f"Unexpected Binance path: {request.url.path}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_binance_signs_and_maps_spot_portfolio() -> None:
    connector = BinanceConnector(
        {"api_key": "test-key", "secret_key": "test-secret"}, transport=_transport()
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 8, 6))

    assert positions[0].ticker == "BTC"
    assert positions[0].asset_type is AssetType.CRYPTO
    assert positions[0].current_value == Decimal("5000.0")
    assert positions[1].asset_type is AssetType.CASH
    assert activity[0].transaction_type is TransactionType.BUY
    assert activity[0].external_id == "trade:BTCEUR:42"
    assert activity[1].transaction_type is TransactionType.FEE
    assert snapshot.total_value == Decimal("5100.0")
    assert snapshot.currency == "EUR"


@pytest.mark.asyncio
async def test_binance_rejects_invalid_credentials_safely() -> None:
    connector = BinanceConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(invalid_credentials=True),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the API key or secret"):
        await connector.validate_credentials()
