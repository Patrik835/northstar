from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.analytics import TargetsUpdate
from app.schemas.performance import PortfolioHistoryPoint
from app.services.analytics import _growth_series


def point(on: date, value: str) -> PortfolioHistoryPoint:
    return PortfolioHistoryPoint(
        date=on,
        total_value_eur=Decimal(value),
        net_invested_eur=Decimal(0),
        invested_value_eur=Decimal(0),
    )


def test_growth_series_does_not_treat_a_deposit_as_investment_return() -> None:
    points = [
        point(date(2026, 1, 1), "1000"),
        point(date(2026, 2, 1), "1500"),
        point(date(2026, 3, 1), "1650"),
    ]

    growth = _growth_series(points, {date(2026, 2, 1): Decimal("500")})

    assert growth == [
        (date(2026, 1, 1), Decimal("100")),
        (date(2026, 2, 1), Decimal("100")),
        (date(2026, 3, 1), Decimal("110")),
    ]


def test_target_allocations_cannot_exceed_one_hundred_percent() -> None:
    with pytest.raises(ValidationError, match="cannot total more than 100%"):
        TargetsUpdate.model_validate(
            {
                "items": [
                    {"holding_key": "one", "target_percentage": "60"},
                    {"holding_key": "two", "target_percentage": "50"},
                ]
            }
        )
