import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument
from app.models.portfolio import Position
from app.repositories.portfolio import HoldingPositionRow
from app.services.portfolio import PortfolioService, company_identity


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
    reported_pnl: str | None = None,
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
        reported_pnl=Decimal(reported_pnl) if reported_pnl is not None else None,
        reported_pnl_eur=Decimal(reported_pnl) if reported_pnl is not None else None,
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
            reported_pnl="75",
        ),
    ]

    result = await PortfolioService(HoldingsRepository(rows)).holdings(uuid.uuid4())

    assert result.total_value_eur == Decimal("1000")
    assert result.reported_pnl_eur == Decimal("75")
    assert result.reported_pnl_position_count == 1
    assert result.instrument_count == 1
    assert result.position_count == 2
    assert result.holdings[0].symbol == "AAPL"
    assert result.holdings[0].total_quantity == Decimal("5")
    assert result.holdings[0].reported_pnl_eur == Decimal("75")
    assert result.holdings[0].reported_pnl_source_count == 1
    assert result.holdings[0].source_count == 2
    assert {source.provider_symbol for source in result.holdings[0].sources} == {
        "AAPL",
        "AAPL_US_EQ",
    }
    etoro_source = next(
        source
        for source in result.holdings[0].sources
        if source.broker is Broker.ETORO
    )
    assert etoro_source.reported_pnl == Decimal("75")
    assert etoro_source.reported_pnl_eur == Decimal("75")


@pytest.mark.asyncio
async def test_holdings_keep_unreported_pnl_unknown_instead_of_zero() -> None:
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
        )
    ]

    result = await PortfolioService(HoldingsRepository(rows)).holdings(uuid.uuid4())

    assert result.reported_pnl_eur is None
    assert result.reported_pnl_position_count == 0
    assert result.holdings[0].reported_pnl_eur is None
    assert result.holdings[0].reported_pnl_source_count == 0


def test_company_identity_ignores_share_class_and_legal_suffixes() -> None:
    assert company_identity("Alphabet") == ("alphabet", "Alphabet")
    assert company_identity("Alphabet (Class A)") == ("alphabet", "Alphabet")
    assert company_identity("Alphabet Inc. Class C") == ("alphabet", "Alphabet Inc")


@pytest.mark.asyncio
async def test_holdings_groups_share_classes_as_one_company_exposure() -> None:
    class_a = Instrument(
        id=uuid.uuid4(),
        identity_key="ISIN:US02079K3059",
        canonical_symbol="GOOGL",
        name="Alphabet (Class A)",
        asset_type=AssetType.STOCK,
        isin="US02079K3059",
    )
    class_c = Instrument(
        id=uuid.uuid4(),
        identity_key="SECURITY:GOOG",
        canonical_symbol="GOOG",
        name="Alphabet",
        asset_type=AssetType.STOCK,
    )
    rows = [
        _row(
            Broker.TRADING212,
            class_a,
            provider_id="US02079K3059",
            ticker="GOOGL_US_EQ",
            quantity="2",
            value="400",
            reported_pnl="40",
        ),
        _row(
            Broker.ETORO,
            class_c,
            provider_id="ETORO:GOOG",
            ticker="GOOG",
            quantity="3",
            value="600",
            reported_pnl="60",
        ),
    ]

    result = await PortfolioService(HoldingsRepository(rows)).holdings(uuid.uuid4())

    assert result.instrument_count == 1
    assert result.position_count == 2
    assert len(result.holdings) == 1
    holding = result.holdings[0]
    assert holding.key == "company:alphabet"
    assert holding.grouping == "company"
    assert holding.instrument_count == 2
    assert holding.canonical_instrument_id is None
    assert holding.symbols == ["GOOG", "GOOGL"]
    assert holding.name == "Alphabet"
    assert holding.isin is None
    assert holding.total_quantity is None
    assert holding.total_value_eur == Decimal("1000")
    assert holding.reported_pnl_eur == Decimal("100")
    assert {source.canonical_symbol for source in holding.sources} == {"GOOG", "GOOGL"}
    assert {
        source.canonical_isin for source in holding.sources
    } == {None, "US02079K3059"}
