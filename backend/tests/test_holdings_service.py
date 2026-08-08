import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument
from app.models.portfolio import Position
from app.repositories.portfolio import ConnectionQualityRow, HoldingPositionRow
from app.services.portfolio import PortfolioService, company_identity


class HoldingsRepository:
    def __init__(self, rows: list[HoldingPositionRow]) -> None:
        self.rows = rows

    async def holding_positions(self, user_id: uuid.UUID) -> list[HoldingPositionRow]:
        return self.rows

    async def connection_quality(self, user_id: uuid.UUID) -> list[ConnectionQualityRow]:
        unique = {row.connection_id: row for row in self.rows}
        return [
            ConnectionQualityRow(
                broker=row.broker,
                connection_id=row.connection_id,
                reconciliation_difference_percent=(
                    row.reconciliation_difference_percent
                ),
                reconciliation_checked_at=row.reconciliation_checked_at,
                reconciliation_warning=row.reconciliation_warning,
            )
            for row in unique.values()
        ]


def _row(
    broker: Broker,
    instrument: Instrument,
    *,
    provider_id: str,
    ticker: str,
    quantity: str,
    value: str,
    reported_pnl: str | None = None,
    synced_at: datetime | None = None,
    is_estimated: bool = False,
    reconciliation_warning: str | None = None,
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
        valued_at=synced_at or datetime.now(timezone.utc),
        valuation_source="last_trade" if is_estimated else "provider",
        is_estimated=is_estimated,
    )
    return HoldingPositionRow(
        position=position,
        broker=broker,
        connection_id=connection_id,
        last_synced_at=synced_at or datetime.now(timezone.utc),
        instrument=instrument,
        reconciliation_difference_percent=(
            Decimal("5") if reconciliation_warning else None
        ),
        reconciliation_checked_at=(
            datetime.now(timezone.utc) if reconciliation_warning else None
        ),
        reconciliation_warning=reconciliation_warning,
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


@pytest.mark.asyncio
async def test_holdings_exposes_stale_estimated_and_reconciliation_status() -> None:
    instrument = Instrument(
        id=uuid.uuid4(),
        identity_key="CRYPTO:BTC",
        canonical_symbol="BTC",
        name="Bitcoin",
        asset_type=AssetType.CRYPTO,
    )
    stale_at = datetime.now(timezone.utc) - timedelta(hours=5)
    warning = (
        "Trading 212 holdings differ from its reported account total by 5.0%. "
        "The latest holdings were preserved."
    )
    rows = [
        _row(
            Broker.TRADING212,
            instrument,
            provider_id="BTC",
            ticker="BTC",
            quantity="1",
            value="100",
            synced_at=stale_at,
            is_estimated=True,
            reconciliation_warning=warning,
        )
    ]

    result = await PortfolioService(
        HoldingsRepository(rows), sync_interval_minutes=120
    ).holdings(uuid.uuid4())

    assert result.as_of == stale_at
    assert result.stale_source_count == 1
    assert result.estimated_position_count == 1
    assert len(result.reconciliation_warnings) == 1
    assert result.reconciliation_warnings[0].message == warning
    holding = result.holdings[0]
    assert holding.is_stale is True
    assert holding.has_estimated_value is True
    assert holding.sources[0].freshness_status == "stale"
    assert holding.sources[0].valuation_source == "last_trade"
