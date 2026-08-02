import base64
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.trading212 import Trading212Connector
from app.models.enums import AssetType, TransactionType


def _transport(status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(b"test-key:test-secret").decode()
        assert request.headers["authorization"] == f"Basic {expected}"
        if status_code != 200:
            return httpx.Response(status_code, request=request)

        if request.url.path.endswith("/account/summary"):
            payload = {
                "currency": "EUR",
                "totalValue": 1350.5,
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
                        "name": "Apple",
                        "ticker": "AAPL_US_EQ",
                    },
                    "walletImpact": {"currency": "EUR", "currentValue": 220.5},
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
    assert positions[1].asset_type is AssetType.CASH
    assert positions[1].current_value == Decimal("115")
    assert activity[0].transaction_type is TransactionType.BUY
    assert activity[0].external_id == "order-fill:42"
    assert snapshot.total_value == Decimal("1350.5")


@pytest.mark.asyncio
async def test_trading212_rejects_invalid_credentials_safely() -> None:
    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=_transport(401),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the API key or secret"):
        await connector.validate_credentials()
