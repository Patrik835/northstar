import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument
from app.models.portfolio import Position
from app.repositories.portfolio import HoldingPositionRow
from app.services.portfolio import PortfolioService


class HoldingsRepository:
    def __init__(self, rows: list[HoldingPositionRow]) -> None:
        self.rows = rows

    async def holding_positions(self, user_id: uuid.UUID) -> list[HoldingPositionRow]:
        return self.rows


def _row(
    broker: Broker,
    instrument: Instrument,
    *,
    provider_id: str,
    ticker: str,
    quantity: str,
    value: str,
) -> HoldingPositionRow:
    connection_id = uuid.uuid4()
    position = Position(
        id=uuid.uuid4(),
        broker_connection_id=connection_id,
        instrument_id=provider_id,
        canonical_instrument_id=instrument.id,
        ticker=ticker,
        name="Apple Inc.",
        asset_type=AssetType.STOCK,
        quantity=Decimal(quantity),
        average_price=Decimal("100"),
        current_value=Decimal(value),
        currency="EUR",
        current_value_eur=Decimal(value),
    )
    return HoldingPositionRow(
        position=position,
        broker=broker,
        connection_id=connection_id,
        last_synced_at=datetime.now(timezone.utc),
        instrument=instrument,
    )


@pytest.mark.asyncio
async def test_holdings_combines_same_instrument_and_preserves_sources() -> None:
    instrument = Instrument(
        id=uuid.uuid4(),
        identity_key="ISIN:US0378331005",
        canonical_symbol="AAPL",
        name="Apple Inc.",
        asset_type=AssetType.STOCK,
        isin="US0378331005",
    )
    rows = [
        _row(
            Broker.TRADING212,
            instrument,
            provider_id="US0378331005",
            ticker="AAPL_US_EQ",
            quantity="2",
            value="400",
        ),
        _row(
            Broker.ETORO,
            instrument,
            provider_id="ETORO:1001",
            ticker="AAPL",
            quantity="3",
            value="600",
        ),
    ]

    result = await PortfolioService(HoldingsRepository(rows)).holdings(uuid.uuid4())

    assert result.total_value_eur == Decimal("1000")
    assert result.instrument_count == 1
    assert result.position_count == 2
    assert result.holdings[0].symbol == "AAPL"
    assert result.holdings[0].total_quantity == Decimal("5")
    assert result.holdings[0].source_count == 2
    assert {source.provider_symbol for source in result.holdings[0].sources} == {
        "AAPL",
        "AAPL_US_EQ",
    }
