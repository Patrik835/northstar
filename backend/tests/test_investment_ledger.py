import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import Broker, TransactionType
from app.models.portfolio import Transaction
from app.repositories.portfolio import TransactionRow
from app.services.investment_ledger import average_cost_ledger


def event(
    kind: TransactionType,
    value: str,
    day: int,
    *,
    quantity: str | None = None,
    value_eur: str | None = None,
) -> TransactionRow:
    connection_id = uuid.uuid4()
    return TransactionRow(
        transaction=Transaction(
            broker_connection_id=connection_id,
            external_id=f"{kind.value}-{day}",
            ticker="AAA",
            transaction_type=kind,
            quantity=Decimal(quantity) if quantity is not None else None,
            price=None,
            value=Decimal(value),
            value_eur=Decimal(value_eur if value_eur is not None else value),
            currency="EUR",
            executed_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        ),
        broker=Broker.TRADING212,
        connection_id=connection_id,
        instrument=None,
    )


def test_average_cost_ledger_preserves_realized_profit_after_reinvestment() -> None:
    result = average_cost_ledger(
        [
            event(TransactionType.BUY, "1000", 1, quantity="10"),
            event(TransactionType.SELL, "1100", 2, quantity="10"),
            event(TransactionType.BUY, "1100", 3, quantity="20"),
        ],
        current_quantity=Decimal("20"),
    )

    assert result.coverage == "complete"
    assert result.cost_basis_eur == Decimal("1100")
    assert result.realized_pnl_eur == Decimal("100")
    assert result.remaining_quantity == Decimal("20")


def test_average_cost_ledger_releases_proportional_cost_and_separates_income_fees() -> None:
    result = average_cost_ledger(
        [
            event(TransactionType.BUY, "100", 1, quantity="10"),
            event(TransactionType.BUY, "200", 2, quantity="10"),
            event(TransactionType.SELL, "100", 3, quantity="5"),
            event(TransactionType.DIVIDEND, "7", 4),
            event(TransactionType.FEE, "2", 5),
        ],
        current_quantity=Decimal("15"),
    )

    assert result.coverage == "complete"
    assert result.cost_basis_eur == Decimal("225")
    assert result.realized_pnl_eur == Decimal("25")
    assert result.income_eur == Decimal("7")
    assert result.fees_eur == Decimal("2")


def test_average_cost_ledger_withholds_results_for_incomplete_trade_values() -> None:
    missing = event(TransactionType.BUY, "100", 1, quantity="10")
    missing.transaction.value_eur = None

    result = average_cost_ledger([missing], current_quantity=Decimal("10"))

    assert result.coverage == "partial"
    assert result.cost_basis_eur is None
    assert result.realized_pnl_eur is None
    assert result.missing_event_count == 1


def test_average_cost_ledger_withholds_results_when_quantity_does_not_reconcile() -> None:
    result = average_cost_ledger(
        [event(TransactionType.BUY, "100", 1, quantity="10")],
        current_quantity=Decimal("9"),
    )

    assert result.coverage == "partial"
    assert result.cost_basis_eur is None
    assert result.realized_pnl_eur is None
    assert result.missing_event_count == 1
