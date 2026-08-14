from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PortfolioHistoryPoint(BaseModel):
    date: date
    total_value_eur: Decimal
    net_invested_eur: Decimal


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
    range: Literal["1m", "3m", "6m", "1y", "all"]
    currency: str = "EUR"
    start_date: date | None
    end_date: date | None
    points: list[PortfolioHistoryPoint]
    money_weighted_return: ReturnMetric
    time_weighted_return: ReturnMetric
    attribution: ReturnAttribution
    missing_fx_transaction_count: int = 0
    notices: list[str] = Field(default_factory=list)
