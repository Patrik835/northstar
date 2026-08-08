import base64
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.connectors.base import BrokerUnavailableError, InvalidBrokerCredentials
from app.integrations.connectors.trading212 import Trading212Connector
from app.models.enums import AssetType, TransactionType


def _transport(
    status_code: int = 200,
    *,
    instrument_name: str = "Apple",
    instrument_type: str = "STOCK",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(b"test-key:test-secret").decode()
        assert request.headers["authorization"] == f"Basic {expected}"
        if status_code != 200:
            return httpx.Response(status_code, request=request)

        if request.url.path.endswith("/account/summary"):
            payload = {
                "currency": "EUR",
                "totalValue": 1350.5,
                "investments": {
                    "currentValue": 1235.5,
                    "realizedProfitLoss": 30,
                    "totalCost": 1100,
                    "unrealizedProfitLoss": 135.5,
                },
                "cash": {
                    "availableToTrade": 100,
                    "inPies": 10,
                    "reservedForOrders": 5,
                },
            }
        elif request.url.path.endswith("/positions"):
            payload = [
                {
                    "averagePricePaid": 100,
                    "quantity": 2,
                    "instrument": {
                        "currency": "USD",
                        "isin": "US0378331005",
                        "name": instrument_name,
                        "ticker": "AAPL_US_EQ",
                    },
                    "walletImpact": {
                        "currency": "EUR",
                        "currentValue": 220.5,
                        "fxImpact": 4.5,
                        "totalCost": 200,
                        "unrealizedProfitLoss": 20.5,
                    },
                }
            ]
        elif request.url.path.endswith("/metadata/instruments"):
            payload = [
                {
                    "currencyCode": "USD",
                    "isin": "US0378331005",
                    "name": instrument_name,
                    "ticker": "AAPL_US_EQ",
                    "type": instrument_type,
                }
            ]
        elif request.url.path.endswith("/history/orders"):
            payload = {
                "items": [
                    {
                        "order": {
                            "id": 41,
                            "side": "BUY",
                            "currency": "EUR",
                            "instrument": {"ticker": "AAPL_US_EQ"},
                        },
                        "fill": {
                            "id": 42,
                            "filledAt": "2026-08-01T10:00:00Z",
                            "quantity": 2,
                            "price": 100,
                            "walletImpact": {"currency": "EUR", "netValue": -200},
                        },
                    }
                ],
                "nextPagePath": None,
            }
        elif request.url.path.endswith("/history/dividends"):
            payload = {"items": [], "nextPagePath": None}
        elif request.url.path.endswith("/history/transactions"):
            payload = {"items": [], "nextPagePath": None}
        else:
            raise AssertionError(f"Unexpected path: {request.url.path}")
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_trading212_validates_and_maps_portfolio() -> None:
    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=_transport(),
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 8, 2))

    assert positions[0].ticker == "AAPL_US_EQ"
    assert positions[0].asset_type is AssetType.STOCK
    assert positions[0].current_value == Decimal("220.5")
    assert positions[0].reported_pnl == Decimal("20.5")
    assert positions[1].asset_type is AssetType.CASH
    assert positions[1].current_value == Decimal("115")
    assert activity[0].transaction_type is TransactionType.BUY
    assert activity[0].external_id == "order-fill:42"
    assert snapshot.total_value == Decimal("1350.5")
    assert snapshot.reported_pnl == Decimal("135.5")


@pytest.mark.asyncio
async def test_trading212_uses_verified_metadata_instead_of_name_guessing() -> None:
    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=_transport(
            instrument_name="Global Market Portfolio",
            instrument_type="ETF",
        ),
    )

    positions = await connector.fetch_positions()

    assert positions[0].name == "Global Market Portfolio"
    assert positions[0].asset_type is AssetType.ETF


@pytest.mark.asyncio
async def test_trading212_rejects_invalid_credentials_safely() -> None:
    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=_transport(401),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the API key or secret"):
        await connector.validate_credentials()


@pytest.mark.asyncio
async def test_trading212_follows_the_provider_next_page_path() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        cursor = request.url.params.get("cursor")
        fill_id = 43 if cursor else 42
        payload = {
            "items": [
                {
                    "order": {
                        "id": fill_id,
                        "side": "BUY",
                        "instrument": {"ticker": "AAPL_US_EQ"},
                    },
                    "fill": {
                        "id": fill_id,
                        "filledAt": "2026-08-01T10:00:00Z",
                        "quantity": 1,
                        "price": 100,
                        "walletImpact": {"currency": "EUR", "netValue": -100},
                    },
                }
            ],
            "nextPagePath": (
                None if cursor else "/api/v0/equity/history/orders?limit=50&cursor=12345"
            ),
        }
        return httpx.Response(200, json=payload, request=request)

    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=httpx.MockTransport(handler),
    )
    first = await connector.fetch_transaction_page("orders")
    second = await connector.fetch_transaction_page("orders", first.next_page_path)

    assert first.transactions[0].external_id == "order-fill:42"
    assert second.transactions[0].external_id == "order-fill:43"
    assert second.next_page_path is None
    assert requested == [
        "https://live.trading212.com/api/v0/equity/history/orders?limit=50",
        "https://live.trading212.com/api/v0/equity/history/orders?limit=50&cursor=12345",
    ]


@pytest.mark.asyncio
async def test_trading212_rejects_an_untrusted_continuation_url() -> None:
    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    )

    with pytest.raises(BrokerUnavailableError, match="invalid history continuation"):
        await connector.fetch_transaction_page("orders", "https://example.com/steal-credentials")


@pytest.mark.asyncio
async def test_trading212_anchors_query_only_continuation_to_stream_endpoint() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            200,
            json={"items": [], "nextPagePath": None},
            request=request,
        )

    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=httpx.MockTransport(handler),
    )
    await connector.fetch_transaction_page(
        "cash", "limit=50&cursor=cursor-id&time=2026-07-16T01:13:32.675Z"
    )

    assert requested == [
        "https://live.trading212.com/api/v0/equity/history/transactions"
        "?limit=50&cursor=cursor-id&time=2026-07-16T01:13:32.675Z"
    ]
