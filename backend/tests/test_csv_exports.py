import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.enums import AssetType, Broker, TransactionType
from app.schemas.activity import (
    ActivityItem,
    ActivityResponse,
    ActivitySummary,
    ActivityTotal,
)
from app.schemas.performance import (
    PortfolioHistoryPoint,
    PortfolioPerformanceResponse,
    ReturnAttribution,
    ReturnMetric,
)
from app.schemas.portfolio import (
    Holding,
    HoldingSource,
    HoldingsResponse,
    InvestmentPerformanceBreakdown,
)
from app.services.csv_exports import (
    csv_document,
    holdings_csv,
    income_csv,
    performance_csv,
    transactions_csv,
)


def rows(document: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(document.decode("utf-8-sig"))))


def empty_total() -> ActivityTotal:
    return ActivityTotal(
        value_eur=Decimal(0),
        event_count=0,
        missing_eur_count=0,
        estimated_eur_count=0,
        native_values=[],
    )


def activity_item(transaction_type: TransactionType, symbol: str) -> ActivityItem:
    return ActivityItem(
        id=uuid.uuid4(),
        broker=Broker.TRADING212,
        connection_id=uuid.uuid4(),
        holding_key=f"company:{symbol.casefold()}",
        symbol=symbol,
        name=f"{symbol} Holdings",
        transaction_type=transaction_type,
        quantity=Decimal("2"),
        price=Decimal("12.50"),
        value=Decimal("25"),
        value_eur=Decimal("23.75"),
        is_estimated_fx=False,
        currency="USD",
        executed_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
    )


def holding_source(broker: Broker, symbol: str, value: str) -> HoldingSource:
    return HoldingSource(
        broker=broker,
        connection_id=uuid.uuid4(),
        provider_instrument_id=symbol,
        provider_symbol=symbol,
        provider_name=f"{symbol} provider name",
        canonical_instrument_id=uuid.uuid4(),
        canonical_symbol=symbol,
        canonical_name=f"{symbol} canonical name",
        canonical_isin=None,
        quantity=Decimal("2"),
        average_price=Decimal("40"),
        current_value=Decimal(value),
        currency="EUR",
        current_value_eur=Decimal(value),
        reported_pnl=Decimal("20"),
        reported_pnl_eur=Decimal("20"),
        instrument_percentage=Decimal("50"),
        last_synced_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        valued_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        valuation_source="provider",
        is_estimated=False,
        freshness_status="fresh",
        is_stale=False,
        performance=InvestmentPerformanceBreakdown(
            cost_basis_eur=Decimal("80"),
            open_pnl_eur=Decimal("20"),
            realized_pnl_eur=Decimal("5"),
            income_eur=Decimal("2"),
            fees_eur=Decimal("1"),
            total_return_eur=Decimal("26"),
            coverage="complete",
        ),
    )


def test_csv_document_is_excel_friendly_and_does_not_turn_text_into_formulas() -> None:
    document = csv_document(
        ["name", "amount"],
        [['=HYPERLINK("https://invalid")', Decimal("-12.50")]],
    )

    assert document.startswith(b"\xef\xbb\xbf")
    assert document.endswith(b"\r\n")
    assert rows(document) == [{"name": '\'=HYPERLINK("https://invalid")', "amount": "-12.50"}]


def test_holdings_export_applies_asset_source_and_search_filters() -> None:
    stock_source = holding_source(Broker.TRADING212, "SAFE", "100")
    crypto_source = holding_source(Broker.BINANCE, "BTC", "200")
    portfolio = HoldingsResponse(
        total_value_eur=Decimal("300"),
        reported_pnl_eur=Decimal("40"),
        reported_pnl_position_count=2,
        instrument_count=2,
        position_count=2,
        unmatched_positions=0,
        as_of=datetime(2026, 8, 15, tzinfo=timezone.utc),
        stale_source_count=0,
        estimated_position_count=0,
        reconciliation_warnings=[],
        sources=[],
        holdings=[
            Holding(
                key="company:safe",
                grouping="company",
                instrument_count=1,
                canonical_instrument_id=stock_source.canonical_instrument_id,
                symbol="SAFE",
                symbols=["SAFE"],
                name="=unsafe spreadsheet name",
                isin=None,
                asset_type=AssetType.STOCK,
                total_quantity=Decimal("2"),
                total_value_eur=Decimal("100"),
                reported_pnl_eur=Decimal("20"),
                reported_pnl_source_count=1,
                portfolio_percentage=Decimal("33.33"),
                source_count=1,
                as_of=stock_source.valued_at,
                is_stale=False,
                stale_source_count=0,
                has_estimated_value=False,
                sources=[stock_source],
            ),
            Holding(
                key="instrument:btc",
                grouping="instrument",
                instrument_count=1,
                canonical_instrument_id=crypto_source.canonical_instrument_id,
                symbol="BTC",
                symbols=["BTC"],
                name="Bitcoin",
                isin=None,
                asset_type=AssetType.CRYPTO,
                total_quantity=Decimal("2"),
                total_value_eur=Decimal("200"),
                reported_pnl_eur=Decimal("20"),
                reported_pnl_source_count=1,
                portfolio_percentage=Decimal("66.67"),
                source_count=1,
                as_of=crypto_source.valued_at,
                is_stale=False,
                stale_source_count=0,
                has_estimated_value=False,
                sources=[crypto_source],
            ),
        ],
    )

    exported = rows(
        holdings_csv(
            portfolio,
            broker=Broker.TRADING212,
            asset_group="equities",
            search="safe",
        )
    )

    assert len(exported) == 1
    assert exported[0]["symbol"] == "SAFE"
    assert exported[0]["name"] == "'=unsafe spreadsheet name"
    assert exported[0]["value_eur"] == "100"
    assert exported[0]["open_pnl_eur"] == "20"
    assert exported[0]["sources"] == "trading212"


def test_transaction_and_income_exports_include_the_expected_events() -> None:
    activity = ActivityResponse(
        items=[
            activity_item(TransactionType.BUY, "MSFT"),
            activity_item(TransactionType.DIVIDEND, "AAPL"),
        ],
        total=2,
        offset=0,
        limit=100,
        brokers=[Broker.TRADING212],
        transaction_types=[TransactionType.BUY, TransactionType.DIVIDEND],
        summary=ActivitySummary(
            bought=empty_total(),
            sold=empty_total(),
            dividends=empty_total(),
            deposited=empty_total(),
        ),
    )

    transaction_rows = rows(transactions_csv(activity))
    income_rows = rows(income_csv(activity))

    assert [item["transaction_type"] for item in transaction_rows] == ["buy", "dividend"]
    assert transaction_rows[0]["value_eur"] == "23.75"
    assert [item["symbol"] for item in income_rows] == ["AAPL"]


def test_performance_export_contains_every_chart_point_and_return_summary() -> None:
    performance = PortfolioPerformanceResponse(
        range="1m",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        points=[
            PortfolioHistoryPoint(
                date=date(2026, 8, day),
                total_value_eur=Decimal(str(1000 + day)),
                net_invested_eur=Decimal("900"),
                invested_value_eur=Decimal("900"),
            )
            for day in (1, 2)
        ],
        money_weighted_return=ReturnMetric(percentage=Decimal("11.2"), status="available"),
        time_weighted_return=ReturnMetric(percentage=Decimal("10.8"), status="available"),
        attribution=ReturnAttribution(
            total_return_eur=Decimal("102"),
            capital_gain_eur=Decimal("98"),
            income_eur=Decimal("5"),
            fees_eur=Decimal("1"),
            currency_movement_eur=Decimal("0"),
            status="available",
        ),
    )

    exported = rows(performance_csv(performance))

    assert [item["date"] for item in exported] == ["2026-08-01", "2026-08-02"]
    assert all(item["range"] == "1m" for item in exported)
    assert exported[0]["money_weighted_return_percentage"] == "11.2"
    assert exported[0]["total_return_eur"] == "102"
