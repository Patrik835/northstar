from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.integrations.connectors.base import InvalidBrokerCredentials
from app.integrations.connectors.interactive_brokers import InteractiveBrokersConnector
from app.models.enums import AssetType, TransactionType

REPORT = b"""<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements count="1">
    <FlexStatement accountId="U123" baseCurrency="EUR">
      <ChangeInNAV currency="EUR" endingValue="12500.50" />
      <OpenPositions>
        <OpenPosition accountId="U123" currency="USD" symbol="AAPL"
          description="Apple Inc" conid="265598" assetCategory="STK"
          securityIDType="ISIN" securityID="US0378331005" position="2"
          positionValue="420" costBasisMoney="350" fifoPnlUnrealized="70" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U123" currency="EUR" endingCash="1000" />
        <CashReportCurrency accountId="U123" currency="BASE_SUMMARY" endingCash="1000" />
      </CashReport>
      <Trades>
        <Trade accountId="U123" levelOfDetail="EXECUTION" currency="USD"
          symbol="AAPL" assetCategory="STK" tradeID="trade-7" buySell="BUY"
          tradeDate="20260810" tradeTime="12:30:00" quantity="2"
          tradePrice="175" proceeds="-350" ibCommission="-1"
          ibCommissionCurrency="USD" />
      </Trades>
      <CashTransactions>
        <CashTransaction accountId="U123" transactionID="cash-8" currency="USD"
          symbol="AAPL" dateTime="20260811;08:00:00" type="Dividends"
          description="AAPL cash dividend" amount="4.25" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def _transport(
    *, invalid: bool = False, requests: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        assert request.headers["User-Agent"] == "NorthstarPortfolio/1.0"
        if request.url.path.endswith("/SendRequest"):
            if invalid:
                return httpx.Response(
                    200,
                    content=b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015</ErrorCode></FlexStatementResponse>",
                    request=request,
                )
            assert request.url.params["t"] == "flex-token"
            assert request.url.params["q"] == "12345"
            return httpx.Response(
                200,
                content=b"<FlexStatementResponse><Status>Success</Status><ReferenceCode>ref-7</ReferenceCode></FlexStatementResponse>",
                request=request,
            )
        if request.url.path.endswith("/GetStatement"):
            assert request.url.params["q"] == "ref-7"
            return httpx.Response(200, content=REPORT, request=request)
        raise AssertionError(f"Unexpected IBKR path: {request.url.path}")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ibkr_flex_maps_positions_cash_pnl_activity_and_nav() -> None:
    requests: list[httpx.Request] = []
    connector = InteractiveBrokersConnector(
        {"flex_token": "flex-token", "query_id": "12345"},
        transport=_transport(requests=requests),
    )

    await connector.validate_credentials()
    positions = await connector.fetch_positions()
    activity = await connector.fetch_transactions(None)
    snapshot = await connector.fetch_snapshot(date(2026, 8, 15))

    stock = next(item for item in positions if item.ticker == "AAPL")
    cash = next(item for item in positions if item.asset_type is AssetType.CASH)
    assert stock.isin == "US0378331005"
    assert stock.quantity == Decimal("2")
    assert stock.average_price == Decimal("175")
    assert stock.reported_pnl == Decimal("70")
    assert cash.current_value == Decimal("1000")
    by_id = {item.external_id: item for item in activity}
    assert by_id["trade:U123:trade-7"].transaction_type is TransactionType.BUY
    assert by_id["trade-fee:U123:trade-7"].value == Decimal("1")
    assert by_id["cash:U123:cash-8"].transaction_type is TransactionType.DIVIDEND
    assert snapshot.total_value == Decimal("12500.50")
    assert snapshot.currency == "EUR"
    assert snapshot.independent_total is True
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_ibkr_flex_rejects_invalid_token_safely() -> None:
    connector = InteractiveBrokersConnector(
        {"flex_token": "bad", "query_id": "12345"},
        transport=_transport(invalid=True),
    )

    with pytest.raises(InvalidBrokerCredentials, match="token is invalid"):
        await connector.validate_credentials()
