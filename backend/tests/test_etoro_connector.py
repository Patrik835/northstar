import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.etoro import EtoroConnector
from app.models.enums import AssetType, TransactionType


def _transport(invalid_credentials: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-api-key"
        assert request.headers["x-user-key"] == "test-user-key"
        uuid.UUID(request.headers["x-request-id"])
        if invalid_credentials:
            return httpx.Response(401, request=request)

        if request.url.path.endswith("/trading/info/aggregate-portfolio"):
            return httpx.Response(
                200,
                json={
                    "cid": 1,
                    "accountCurrency": "USD",
                    "accountTotals": {
                        "accountAvailableCash": 100,
                        "accountTotalValue": 850,
                    },
                    "instrumentAggregates": [
                        {
                            "instrumentId": 1001,
                            "netUnits": 5,
                            "netAvgOpenRate": 100,
                            "liquidationValueAccountCurrency": 500,
                        }
                    ],
                    "mirrors": [
                        {
                            "mirrorId": 77,
                            "mirrorTotals": {"mirrorLiquidationValue": 250},
                        }
                    ],
                },
                request=request,
            )
        if request.url.path.endswith("/trading/info/real/pnl"):
            return httpx.Response(
                200,
                json={
                    "clientPortfolio": {
                        "positions": [
                            {
                                "instrumentID": 1001,
                                "mirrorID": 0,
                                "unrealizedPnL": {"pnL": 55},
                            },
                            {
                                "instrumentID": 1001,
                                "mirrorID": 0,
                                "unrealizedPnL": {"pnL": -15},
                            },
                        ],
                        "mirrors": [
                            {
                                "mirrorID": 77,
                                "closedPositionsNetProfit": 5,
                                "positions": [
                                    {"unrealizedPnL": {"pnL": 20}}
                                ],
                            }
                        ],
                        "unrealizedPnL": 65,
                    }
                },
                request=request,
            )
        if request.url.path.endswith("/market-data/instruments"):
            return httpx.Response(
                200,
                json={
                    "instrumentDisplayDatas": [
                        {
                            "instrumentID": 1001,
                            "instrumentDisplayName": "Apple",
                            "instrumentTypeID": 5,
                            "symbolFull": "AAPL",
                        }
                    ]
                },
                request=request,
            )
        if request.url.path.endswith("/market-data/instrument-types"):
            return httpx.Response(
                200,
                json={
                    "instrumentTypes": [
                        {"instrumentTypeID": 5, "instrumentTypeDescription": "Stocks"}
                    ]
                },
                request=request,
            )
        if request.url.path.endswith("/trading/info/trade/history"):
            assert request.url.params["minDate"]
            return httpx.Response(
                200,
                json=[
                    {
                        "positionId": 99,
                        "instrumentId": 1001,
                        "isBuy": True,
                        "closeRate": 120,
                        "closeTimestamp": "2026-08-01T10:00:00Z",
                        "investment": 500,
                        "netProfit": 100,
                        "fees": 2,
                        "units": 5,
                    }
                ],
                request=request,
            )
        raise AssertionError(f"Unexpected eToro path: {request.url.path}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_etoro_maps_current_portfolio_and_history() -> None:
    connector = EtoroConnector(
        {"api_key": "test-api-key", "user_key": "test-user-key"},
        transport=_transport(),
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 8, 6))

    assert positions[0].ticker == "AAPL"
    assert positions[0].asset_type is AssetType.STOCK
    assert positions[0].current_value == Decimal("500")
    assert positions[0].reported_pnl == Decimal("40")
    assert positions[1].asset_type is AssetType.CASH
    assert positions[1].reported_pnl is None
    assert positions[2].instrument_id == "ETORO:COPY:77"
    assert positions[2].reported_pnl == Decimal("25")
    assert activity[0].transaction_type is TransactionType.SELL
    assert activity[0].value == Decimal("600")
    assert activity[1].transaction_type is TransactionType.FEE
    assert snapshot.total_value == Decimal("850")
    assert snapshot.independent_total is True
    assert snapshot.currency == "USD"
    assert snapshot.reported_pnl == Decimal("65")


@pytest.mark.asyncio
async def test_etoro_rejects_invalid_credentials_safely() -> None:
    connector = EtoroConnector(
        {"api_key": "test-api-key", "user_key": "test-user-key"},
        transport=_transport(invalid_credentials=True),
    )

    with pytest.raises(InvalidBrokerCredentials, match="rejected the Public Key or Private Key"):
        await connector.validate_credentials()
