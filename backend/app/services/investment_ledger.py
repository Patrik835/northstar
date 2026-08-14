from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import TransactionType
from app.repositories.portfolio import TransactionRow


@dataclass(frozen=True, slots=True)
class AverageCostLedger:
    """Performance ledger for one instrument held at one source.

    This is an investment-performance calculation, not a tax-lot calculation.
    A numeric cost basis or realized result is returned only when every required
    trade has an EUR value and the reconstructed quantity matches the position.
    """

    cost_basis_eur: Decimal | None
    realized_pnl_eur: Decimal | None
    income_eur: Decimal
    fees_eur: Decimal
    remaining_quantity: Decimal
    coverage: str
    missing_event_count: int
    trade_count: int


def average_cost_ledger(
    rows: list[TransactionRow], current_quantity: Decimal
) -> AverageCostLedger:
    quantity = Decimal(0)
    cost = Decimal(0)
    realized = Decimal(0)
    income = Decimal(0)
    fees = Decimal(0)
    missing = 0
    trade_count = 0
    trade_values_complete = True

    for row in sorted(
        rows,
        key=lambda item: (
            item.transaction.executed_at,
            str(item.transaction.external_id),
        ),
    ):
        item = row.transaction
        value_eur = abs(item.value_eur) if item.value_eur is not None else None

        if item.transaction_type is TransactionType.DIVIDEND:
            if value_eur is None:
                missing += 1
            else:
                income += value_eur
            continue
        if item.transaction_type is TransactionType.FEE:
            if value_eur is None:
                missing += 1
            else:
                fees += value_eur
            continue
        if item.transaction_type not in {TransactionType.BUY, TransactionType.SELL}:
            continue

        trade_count += 1
        item_quantity = abs(item.quantity or Decimal(0))
        if not item_quantity:
            trade_values_complete = False
            missing += 1
            continue

        if item.transaction_type is TransactionType.BUY:
            quantity += item_quantity
            if value_eur is None:
                trade_values_complete = False
                missing += 1
            elif trade_values_complete:
                cost += value_eur
            continue

        # SELL: weighted-average cost is released in proportion to the quantity sold.
        if value_eur is None:
            trade_values_complete = False
            missing += 1
        if quantity <= 0 or item_quantity > quantity:
            trade_values_complete = False
            missing += 1
            quantity = max(Decimal(0), quantity - item_quantity)
            continue
        released_cost = cost * item_quantity / quantity if trade_values_complete else None
        quantity -= item_quantity
        if released_cost is not None and value_eur is not None:
            cost -= released_cost
            realized += value_eur - released_cost

    tolerance = max(Decimal("0.000001"), abs(current_quantity) * Decimal("0.001"))
    quantity_matches = abs(quantity - current_quantity) <= tolerance
    if not trade_count:
        coverage = "unavailable"
    elif trade_values_complete and quantity_matches:
        coverage = "complete"
    else:
        coverage = "partial"

    return AverageCostLedger(
        cost_basis_eur=cost if coverage == "complete" else None,
        realized_pnl_eur=realized if coverage == "complete" else None,
        income_eur=income,
        fees_eur=fees,
        remaining_quantity=quantity,
        coverage=coverage,
        missing_event_count=missing + (1 if trade_count and not quantity_matches else 0),
        trade_count=trade_count,
    )
