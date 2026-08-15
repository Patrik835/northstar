from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

PerformanceRange = Literal["1w", "1m", "3m", "6m", "1y", "5y", "all"]


class PortfolioHistoryPoint(BaseModel):
    date: date
    total_value_eur: Decimal
    net_invested_eur: Decimal
    invested_value_eur: Decimal


class ReturnMetric(BaseModel):
    percentage: Decimal | None
    status: Literal["available", "partial", "unavailable"]
    message: str | None = None


class ReturnAttribution(BaseModel):
    total_return_eur: Decimal | None
    capital_gain_eur: Decimal | None
    income_eur: Decimal
    fees_eur: Decimal
    currency_movement_eur: Decimal | None
    status: Literal["available", "estimated", "partial", "unavailable"]
    message: str | None = None


class PortfolioPerformanceResponse(BaseModel):
    range: PerformanceRange
    currency: str = "EUR"
    start_date: date | None
    end_date: date | None
    sampling: Literal[
        "daily", "weekly_average", "monthly_average", "adaptive_average"
    ] = "daily"
    history_method: Literal["observed", "reconstructed"] = "observed"
    points: list[PortfolioHistoryPoint]
    money_weighted_return: ReturnMetric
    time_weighted_return: ReturnMetric
    attribution: ReturnAttribution
    missing_fx_transaction_count: int = 0
    notices: list[str] = Field(default_factory=list)
