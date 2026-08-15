import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.performance import PerformanceRange
from app.schemas.portfolio import AllocationItem

Coverage = Literal["available", "partial", "unavailable"]


class AllocationBreakdown(BaseModel):
    dimension: Literal["asset_type", "holding", "broker", "currency", "sector", "geography"]
    items: list[AllocationItem]
    scope_value_eur: Decimal
    covered_value_eur: Decimal
    coverage_percentage: Decimal
    status: Coverage
    message: str | None = None


class Performer(BaseModel):
    holding_key: str
    symbol: str
    name: str
    current_value_eur: Decimal
    open_pnl_eur: Decimal
    open_pnl_percentage: Decimal
    contribution_percentage_points: Decimal
    source: Literal["provider", "calculated", "mixed"]


class PerformanceLeaders(BaseModel):
    best: list[Performer]
    worst: list[Performer]
    contributors: list[Performer]
    coverage_percentage: Decimal
    message: str


class BenchmarkOption(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    name: str


class BenchmarkPoint(BaseModel):
    date: str
    portfolio_return_percentage: Decimal
    benchmark_return_percentage: Decimal


class BenchmarkAnalytics(BaseModel):
    selected_instrument_id: uuid.UUID | None
    selected_symbol: str | None
    selected_name: str | None
    options: list[BenchmarkOption]
    points: list[BenchmarkPoint]
    portfolio_return_percentage: Decimal | None
    benchmark_return_percentage: Decimal | None
    relative_return_percentage: Decimal | None
    status: Coverage
    message: str


class RiskAnalytics(BaseModel):
    maximum_drawdown_percentage: Decimal | None
    annualized_volatility_percentage: Decimal | None
    largest_holding_percentage: Decimal
    top_five_percentage: Decimal
    concentration_hhi: Decimal
    effective_holdings: Decimal
    diversification_score: Decimal
    observation_count: int
    status: Coverage
    message: str


class TargetDriftItem(BaseModel):
    holding_key: str
    symbol: str
    name: str
    current_percentage: Decimal
    target_percentage: Decimal | None
    drift_percentage_points: Decimal | None
    current_value_eur: Decimal
    target_value_eur: Decimal | None
    difference_eur: Decimal | None
    action: Literal["add", "reduce", "on_target", "not_set"]


class TargetAnalytics(BaseModel):
    target_total_percentage: Decimal
    unallocated_percentage: Decimal
    items: list[TargetDriftItem]
    message: str


class AnalyticsResponse(BaseModel):
    range: PerformanceRange
    allocations: list[AllocationBreakdown]
    performance: PerformanceLeaders
    benchmark: BenchmarkAnalytics
    risk: RiskAnalytics
    targets: TargetAnalytics


class BenchmarkUpdate(BaseModel):
    instrument_id: uuid.UUID | None = None


class TargetValue(BaseModel):
    holding_key: str
    target_percentage: Decimal | None = Field(default=None, ge=0, le=100)


class TargetsUpdate(BaseModel):
    items: list[TargetValue] = Field(max_length=250)

    @model_validator(mode="after")
    def target_total_does_not_exceed_one_hundred(self) -> "TargetsUpdate":
        total = sum(
            (item.target_percentage or Decimal(0) for item in self.items), Decimal(0)
        )
        if total > 100:
            raise ValueError("Target allocations cannot total more than 100%")
        if len({item.holding_key for item in self.items}) != len(self.items):
            raise ValueError("Each holding may appear only once")
        return self
