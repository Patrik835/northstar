import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.enums import Broker, TransactionType
from app.models.instrument import Instrument
from app.models.market_data import FxRate, HistoricalPrice
from app.models.portfolio import PortfolioSnapshot, Transaction
from app.repositories.portfolio import HistoricalPriceRow, SnapshotRow, TransactionRow
from app.schemas.performance import PortfolioHistoryPoint
from app.services.performance import (
    PerformanceService,
    _reconstruct_weekly_history,
    _sample_history_points,
)


class PerformanceRepository:
    def __init__(
        self, snapshots: list[SnapshotRow], transactions: list[TransactionRow]
    ) -> None:
        self.snapshots = snapshots
        self.transactions = transactions

    async def snapshot_rows(self, _user_id: uuid.UUID) -> list[SnapshotRow]:
        return self.snapshots

    async def transaction_rows(self, _user_id: uuid.UUID) -> list[TransactionRow]:
        return self.transactions


def snapshot(
    connection_id: uuid.UUID,
    snapshot_date: date,
    value: str,
    reported_pnl: str | None = None,
) -> SnapshotRow:
    return SnapshotRow(
        snapshot=PortfolioSnapshot(
            broker_connection_id=connection_id,
            snapshot_date=snapshot_date,
            total_value=Decimal(value),
            currency="EUR",
            total_value_eur=Decimal(value),
            reported_pnl=(Decimal(reported_pnl) if reported_pnl is not None else None),
            reported_pnl_eur=(Decimal(reported_pnl) if reported_pnl is not None else None),
        ),
        broker=Broker.TRADING212,
        connection_id=connection_id,
    )


def transaction(
    connection_id: uuid.UUID,
    transaction_type: TransactionType,
    value: str,
    executed_at: datetime,
) -> TransactionRow:
    return TransactionRow(
        transaction=Transaction(
            broker_connection_id=connection_id,
            external_id=f"{transaction_type.value}-{executed_at.isoformat()}",
            ticker="CASH",
            transaction_type=transaction_type,
            quantity=None,
            price=None,
            value=Decimal(value),
            value_eur=Decimal(value),
            currency="EUR",
            executed_at=executed_at,
        ),
        broker=Broker.TRADING212,
        connection_id=connection_id,
        instrument=None,
    )


def test_one_year_history_is_sampled_to_52_averaged_points() -> None:
    points = [
        PortfolioHistoryPoint(
            date=date(2025, 8, 14) + (index * (date(2025, 8, 15) - date(2025, 8, 14))),
            total_value_eur=Decimal(index + 1),
            net_invested_eur=Decimal((index + 1) * 2),
            invested_value_eur=Decimal(index + 1),
        )
        for index in range(366)
    ]

    sampled, sampling = _sample_history_points(points, "1y")

    assert sampling == "weekly_average"
    assert len(sampled) == 52
    assert sampled[0].total_value_eur == Decimal("4.00")
    assert sampled[0].net_invested_eur == Decimal("8.00")
    assert sampled[-1].date == points[-1].date


def test_short_history_is_not_artificially_expanded() -> None:
    points = [
        PortfolioHistoryPoint(
            date=date(2026, 8, 12 + index),
            total_value_eur=Decimal("1000") + index,
            net_invested_eur=Decimal("900"),
            invested_value_eur=Decimal("800"),
        )
        for index in range(3)
    ]

    sampled, sampling = _sample_history_points(points, "5y")

    assert sampled == points
    assert sampling == "daily"


def test_weekly_history_reconstruction_links_to_first_observed_value() -> None:
    instrument = Instrument(
        identity_key="isin:US5949181045",
        canonical_symbol="MSFT",
        name="Microsoft",
        asset_type="stock",
        isin="US5949181045",
    )
    trade = transaction(
        uuid.uuid4(),
        TransactionType.BUY,
        "500",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    trade.transaction.ticker = "MSFT"
    trade.transaction.quantity = Decimal("10")
    trade.transaction.currency = "USD"
    trade.transaction.value_eur = None
    trade = TransactionRow(
        transaction=trade.transaction,
        broker=trade.broker,
        connection_id=trade.connection_id,
        instrument=instrument,
    )
    prices = [
        HistoricalPriceRow(
            price=HistoricalPrice(
                instrument_id=instrument.id,
                price_date=price_date,
                close_price=Decimal(close),
                currency="USD",
                source="ALPHA_VANTAGE",
                interval="weekly",
            ),
            instrument=instrument,
        )
        for price_date, close in [
            (date(2026, 1, 3), "60"),
            (date(2026, 1, 10), "70"),
        ]
    ]
    rates = [
        FxRate(
            source="ALPHA_VANTAGE",
            rate_date=price_date,
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.9"),
        )
        for price_date in [
            date(2025, 12, 26),
            date(2026, 1, 3),
            date(2026, 1, 10),
        ]
    ]
    anchor = PortfolioHistoryPoint(
        date=date(2026, 1, 15),
        total_value_eur=Decimal("700"),
        net_invested_eur=Decimal("500"),
        invested_value_eur=Decimal("500"),
    )

    points = _reconstruct_weekly_history(
        prices,
        rates,
        [trade],
        date(2026, 1, 1),
        date(2026, 1, 15),
        anchor,
    )

    assert [point.total_value_eur for point in points] == [
        Decimal("600.00"),
        Decimal("700.00"),
    ]
    assert all(point.invested_value_eur == Decimal("500.00") for point in points)


@pytest.mark.asyncio
async def test_invested_value_uses_broker_reported_open_pnl() -> None:
    connection_id = uuid.uuid4()
    result = await PerformanceService(
        PerformanceRepository(
            [
                snapshot(connection_id, date(2026, 8, 13), "1000", "100"),
                snapshot(connection_id, date(2026, 8, 14), "1100", "150"),
            ],
            [],
        )  # type: ignore[arg-type]
    ).portfolio(uuid.uuid4(), "all")

    assert [point.invested_value_eur for point in result.points] == [
        Decimal("900.00"),
        Decimal("950.00"),
    ]


@pytest.mark.asyncio
async def test_performance_builds_history_returns_and_attribution() -> None:
    connection_id = uuid.uuid4()
    rows = [
        snapshot(connection_id, date(2026, 8, 10), "1000"),
        snapshot(connection_id, date(2026, 8, 11), "1110"),
        snapshot(connection_id, date(2026, 8, 12), "1120"),
    ]
    activity = [
        transaction(
            connection_id,
            TransactionType.DEPOSIT,
            "100",
            datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        ),
        transaction(
            connection_id,
            TransactionType.DIVIDEND,
            "5",
            datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
        ),
    ]

    result = await PerformanceService(
        PerformanceRepository(rows, activity)  # type: ignore[arg-type]
    ).portfolio(uuid.uuid4(), "all")

    assert [point.total_value_eur for point in result.points] == [
        Decimal("1000.00"),
        Decimal("1110.00"),
        Decimal("1120.00"),
    ]
    assert [point.net_invested_eur for point in result.points] == [
        Decimal("1000.00"),
        Decimal("1100.00"),
        Decimal("1100.00"),
    ]
    assert result.time_weighted_return.percentage == Decimal("1.91")
    assert result.money_weighted_return.percentage is not None
    assert result.attribution.total_return_eur == Decimal("20.00")
    assert result.attribution.income_eur == Decimal("5.00")
    assert result.attribution.capital_gain_eur == Decimal("15.00")


@pytest.mark.asyncio
async def test_performance_marks_missing_eur_cash_flow_as_partial() -> None:
    connection_id = uuid.uuid4()
    activity = transaction(
        connection_id,
        TransactionType.DEPOSIT,
        "100",
        datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
    )
    activity.transaction.value_eur = None
    result = await PerformanceService(
        PerformanceRepository(
            [
                snapshot(connection_id, date(2026, 8, 10), "1000"),
                snapshot(connection_id, date(2026, 8, 12), "1020"),
            ],
            [activity],
        )  # type: ignore[arg-type]
    ).portfolio(uuid.uuid4(), "all")

    assert result.missing_fx_transaction_count == 1
    assert result.time_weighted_return.status == "partial"
    assert result.attribution.status == "partial"


@pytest.mark.asyncio
async def test_history_starts_with_complete_source_coverage_and_estimates_opening_capital() -> None:
    first_connection = uuid.uuid4()
    second_connection = uuid.uuid4()
    result = await PerformanceService(
        PerformanceRepository(
            [
                snapshot(first_connection, date(2026, 8, 1), "1000"),
                snapshot(first_connection, date(2026, 8, 5), "1050"),
                snapshot(second_connection, date(2026, 8, 5), "500"),
                snapshot(first_connection, date(2026, 8, 6), "1060"),
                snapshot(second_connection, date(2026, 8, 6), "510"),
            ],
            [],
        )  # type: ignore[arg-type]
    ).portfolio(uuid.uuid4(), "all")

    assert result.start_date == date(2026, 8, 5)
    assert [point.total_value_eur for point in result.points] == [
        Decimal("1550.00"),
        Decimal("1570.00"),
    ]
    assert [point.net_invested_eur for point in result.points] == [
        Decimal("1500.00"),
        Decimal("1500.00"),
    ]
    assert any("Opening capital is estimated" in notice for notice in result.notices)
