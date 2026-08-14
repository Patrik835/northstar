import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.enums import Broker, TransactionType
from app.models.portfolio import PortfolioSnapshot, Transaction
from app.repositories.portfolio import SnapshotRow, TransactionRow
from app.services.performance import PerformanceService


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
    connection_id: uuid.UUID, snapshot_date: date, value: str
) -> SnapshotRow:
    return SnapshotRow(
        snapshot=PortfolioSnapshot(
            broker_connection_id=connection_id,
            snapshot_date=snapshot_date,
            total_value=Decimal(value),
            currency="EUR",
            total_value_eur=Decimal(value),
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
