from decimal import Decimal

from app.services.portfolio import percentage


def test_percentage_rounds_for_display() -> None:
    assert percentage(Decimal("1"), Decimal("3")) == Decimal("33.33")
    assert percentage(Decimal("5"), Decimal("0")) == Decimal("0")
