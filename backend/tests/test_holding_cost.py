import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import Broker, TransactionType
from app.models.portfolio import Transaction
from app.repositories.portfolio import TransactionRow
from app.services.portfolio import _calculated_cost


def activity(kind: TransactionType, quantity: str, value: str, day: int) -> TransactionRow:
    connection_id = uuid.uuid4()
    return TransactionRow(
        transaction=Transaction(
            broker_connection_id=connection_id,
            external_id=f"{kind.value}-{day}",
            ticker="AAA",
            transaction_type=kind,
            quantity=Decimal(quantity),
            price=None,
            value=Decimal(value),
            value_eur=Decimal(value),
            currency="EUR",
            executed_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        ),
        broker=Broker.TRADING212,
        connection_id=connection_id,
        instrument=None,
    )


def test_calculated_cost_uses_moving_average_after_sale() -> None:
    result = _calculated_cost(
        [
            activity(TransactionType.BUY, "10", "100", 1),
            activity(TransactionType.BUY, "10", "200", 2),
            activity(TransactionType.SELL, "5", "100", 3),
        ],
        current_quantity=Decimal("15"),
        current_value_eur=Decimal("300"),
    )

    assert result.cost_eur == Decimal("225")
    assert result.gain_eur == Decimal("75")
    assert result.gain_percentage == Decimal("33.33")
    assert result.coverage == "complete"


def test_calculated_cost_does_not_publish_partial_gain() -> None:
    complete_buy = activity(TransactionType.BUY, "10", "100", 1)
    missing_fx_buy = activity(TransactionType.BUY, "5", "50", 2)
    missing_fx_buy.transaction.value_eur = None

    result = _calculated_cost(
        [complete_buy, missing_fx_buy],
        current_quantity=Decimal("15"),
        current_value_eur=Decimal("130"),
    )

    assert result.cost_eur is None
    assert result.gain_eur is None
    assert result.gain_percentage is None
    assert result.coverage == "partial"


def test_calculated_cost_does_not_publish_gain_when_quantity_does_not_reconcile() -> None:
    result = _calculated_cost(
        [activity(TransactionType.BUY, "10", "100", 1)],
        current_quantity=Decimal("15"),
        current_value_eur=Decimal("130"),
    )

    assert result.cost_eur is None
    assert result.gain_eur is None
    assert result.gain_percentage is None
    assert result.coverage == "partial"
