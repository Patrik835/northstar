import hashlib
import hmac
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode

import httpx
import pytest

from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.binance import BinanceConnector
from app.models.enums import AssetType, TransactionType


def _transport(
    invalid_credentials: bool = False,
    requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
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
                        },
                        {
                            "symbol": "ETHEUR",
                            "status": "TRADING",
                            "baseAsset": "ETH",
                            "quoteAsset": "EUR",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path == "/api/v3/ticker/price":
            return httpx.Response(
                200,
                json=[
                    {"symbol": "BTCEUR", "price": "50000"},
                    {"symbol": "ETHEUR", "price": "2500"},
                ],
                request=request,
            )
        if request.url.path == "/sapi/v1/capital/deposit/hisrec":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "deposit-7",
                        "amount": "1.25",
                        "coin": "ETH",
                        "status": 1,
                        "insertTime": 1_797_000_000_000,
                    },
                    {
                        "id": "pending-deposit",
                        "amount": "2",
                        "coin": "ETH",
                        "status": 0,
                        "insertTime": 1_797_000_000_100,
                    },
                ],
                request=request,
            )
        if request.url.path == "/sapi/v1/capital/withdraw/history":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "withdrawal-8",
                        "amount": "0.4",
                        "transactionFee": "0.002",
                        "coin": "ETH",
                        "status": 6,
                        "completeTime": "2027-01-09 12:30:00",
                    },
                    {
                        "id": "failed-withdrawal",
                        "amount": "3",
                        "transactionFee": "0.01",
                        "coin": "ETH",
                        "status": 3,
                        "completeTime": "2027-01-09 12:31:00",
                    },
                ],
                request=request,
            )
        if request.url.path == "/sapi/v1/asset/assetDividend":
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "id": 73,
                            "amount": "0.0002",
                            "asset": "BTC",
                            "divTime": 1_798_000_000_000,
                            "direction": 1,
                        }
                    ],
                    "total": 1,
                },
                request=request,
            )
        if request.url.path == "/api/v3/myTrades":
            if request.url.params["symbol"] == "ETHEUR":
                return httpx.Response(200, json=[], request=request)
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
    requests: list[httpx.Request] = []
    connector = BinanceConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(requests=requests),
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 8, 6))

    assert positions[0].ticker == "BTC"
    assert positions[0].asset_type is AssetType.CRYPTO
    assert positions[0].current_value == Decimal("5000.0")
    assert positions[1].asset_type is AssetType.CASH
    by_id = {item.external_id: item for item in activity}
    assert by_id["trade:BTCEUR:42"].transaction_type is TransactionType.BUY
    assert by_id["trade-fee:BTCEUR:42"].transaction_type is TransactionType.FEE
    assert by_id["deposit:deposit-7"].transaction_type is TransactionType.DEPOSIT
    assert by_id["withdrawal:withdrawal-8"].transaction_type is TransactionType.WITHDRAWAL
    assert by_id["withdrawal-fee:withdrawal-8"].value == Decimal("0.002")
    assert by_id["income:BTC:73"].transaction_type is TransactionType.DIVIDEND
    assert "deposit:pending-deposit" not in by_id
    assert "withdrawal:failed-withdrawal" not in by_id
    trade_symbols = {
        request.url.params["symbol"]
        for request in requests
        if request.url.path == "/api/v3/myTrades"
    }
    assert trade_symbols == {"BTCEUR", "ETHEUR"}
    assert snapshot.total_value == Decimal("5100.0")
    assert snapshot.currency == "EUR"


@pytest.mark.asyncio
async def test_binance_activity_sync_overlaps_and_filters_previous_records() -> None:
    requests: list[httpx.Request] = []
    connector = BinanceConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(requests=requests),
    )

    activity = await connector.fetch_transactions(
        datetime(2027, 1, 16, tzinfo=timezone.utc)
    )

    assert activity == []
    signed_history_requests = [
        request
        for request in requests
        if request.url.path
        in {
            "/api/v3/myTrades",
            "/sapi/v1/capital/deposit/hisrec",
            "/sapi/v1/capital/withdraw/history",
            "/sapi/v1/asset/assetDividend",
        }
    ]
    assert signed_history_requests
    assert all("startTime" in request.url.params for request in signed_history_requests)


@pytest.mark.asyncio
async def test_binance_rejects_invalid_credentials_safely() -> None:
    connector = BinanceConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(invalid_credentials=True),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the API key or secret"):
        await connector.validate_credentials()
