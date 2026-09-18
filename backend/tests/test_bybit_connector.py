import hashlib
import hmac
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.connectors.base import BrokerPermissionError, InvalidBrokerCredentials
from app.integrations.connectors.bybit import BybitConnector
from app.models.enums import AssetType, TransactionType


def _response(request: httpx.Request, result: dict, ret_code: int = 0) -> httpx.Response:
    return httpx.Response(
        200,
        json={"retCode": ret_code, "retMsg": "OK", "result": result},
        request=request,
    )


def _transport(
    *,
    read_only: int = 1,
    invalid_credentials: bool = False,
    requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        signed_prefixes = ("/v5/user/", "/v5/account/", "/v5/asset/", "/v5/execution/")
        if request.url.path.startswith(signed_prefixes):
            assert request.headers["X-BAPI-API-KEY"] == "test-key"
            timestamp = request.headers["X-BAPI-TIMESTAMP"]
            receive_window = request.headers["X-BAPI-RECV-WINDOW"]
            query = request.url.query.decode()
            expected = hmac.new(
                b"test-secret",
                f"{timestamp}test-key{receive_window}{query}".encode(),
                hashlib.sha256,
            ).hexdigest()
            assert request.headers["X-BAPI-SIGN"] == expected

        if request.url.path == "/v5/user/query-api":
            if invalid_credentials:
                return _response(request, {}, ret_code=10003)
            return _response(request, {"readOnly": read_only})
        if request.url.path == "/v5/account/wallet-balance":
            return _response(
                request,
                {
                    "list": [
                        {
                            "coin": [
                                {"coin": "BTC", "equity": "0.1", "usdValue": "6000"},
                                {"coin": "USDC", "equity": "100", "usdValue": "100"},
                            ]
                        }
                    ]
                },
            )
        if request.url.path == "/v5/asset/transfer/query-account-coins-balance":
            return _response(
                request,
                {"balance": [{"coin": "ETH", "walletBalance": "2"}]},
            )
        if request.url.path == "/v5/market/instruments-info":
            return _response(
                request,
                {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "baseCoin": "BTC",
                            "quoteCoin": "USDT",
                            "status": "Trading",
                        },
                        {
                            "symbol": "ETHUSDT",
                            "baseCoin": "ETH",
                            "quoteCoin": "USDT",
                            "status": "Trading",
                        },
                    ]
                },
            )
        if request.url.path == "/v5/market/tickers":
            return _response(
                request,
                {
                    "list": [
                        {"symbol": "BTCUSDT", "lastPrice": "60000"},
                        {"symbol": "ETHUSDT", "lastPrice": "3000"},
                    ]
                },
            )
        if request.url.path == "/v5/execution/list":
            return _response(
                request,
                {
                    "list": [
                        {
                            "execId": "trade-1",
                            "orderId": "order-1",
                            "symbol": "BTCUSDT",
                            "side": "Buy",
                            "execPrice": "50000",
                            "execQty": "0.01",
                            "execValue": "500",
                            "execFee": "0.00001",
                            "feeCurrency": "BTC",
                            "execTime": "1799000000000",
                        }
                    ],
                    "nextPageCursor": "",
                },
            )
        if request.url.path == "/v5/asset/deposit/query-record":
            return _response(
                request,
                {
                    "rows": [
                        {
                            "id": "deposit-1",
                            "coin": "ETH",
                            "amount": "1.5",
                            "status": 3,
                            "successAt": "1798000000000",
                        }
                    ],
                    "nextPageCursor": "",
                },
            )
        if request.url.path == "/v5/asset/withdraw/query-record":
            return _response(
                request,
                {
                    "rows": [
                        {
                            "withdrawId": "withdraw-1",
                            "coin": "ETH",
                            "amount": "0.2",
                            "withdrawFee": "0.001",
                            "status": "success",
                            "updateTime": "1797000000000",
                        }
                    ],
                    "nextPageCursor": "",
                },
            )
        raise AssertionError(f"Unexpected Bybit path: {request.url.path}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_bybit_signs_requests_and_maps_portfolio_and_activity() -> None:
    requests: list[httpx.Request] = []
    connector = BybitConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(requests=requests),
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 9, 18))

    by_ticker = {item.ticker: item for item in positions}
    assert by_ticker["BTC"].quantity == Decimal("0.1")
    assert by_ticker["BTC"].current_value == Decimal("6000")
    assert by_ticker["BTC"].asset_type is AssetType.CRYPTO
    assert by_ticker["ETH"].quantity == Decimal("2")
    assert by_ticker["ETH"].current_value == Decimal("6000")
    assert snapshot.total_value == Decimal("12100")
    assert snapshot.currency == "USD"

    by_id = {item.external_id: item for item in activity}
    assert by_id["trade:trade-1"].transaction_type is TransactionType.BUY
    assert by_id["trade-fee:trade-1"].currency == "BTC"
    assert by_id["deposit:deposit-1"].transaction_type is TransactionType.DEPOSIT
    assert by_id["withdrawal:withdraw-1"].transaction_type is TransactionType.WITHDRAWAL
    assert by_id["withdrawal-fee:withdraw-1"].value == Decimal("0.001")
    assert any(request.url.host == "api.bybit.eu" for request in requests)


@pytest.mark.asyncio
async def test_bybit_rejects_read_write_key() -> None:
    connector = BybitConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(read_only=0),
    )

    with pytest.raises(BrokerPermissionError, match="only a read-only"):
        await connector.validate_credentials()


@pytest.mark.asyncio
async def test_bybit_rejects_invalid_credentials_safely() -> None:
    connector = BybitConnector(
        {"api_key": "test-key", "secret_key": "test-secret"},
        transport=_transport(invalid_credentials=True),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the API key or secret"):
        await connector.validate_credentials()
