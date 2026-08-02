from decimal import Decimal

from pydantic import BaseModel


class AllocationItem(BaseModel):
    label: str
    value_eur: Decimal
    percentage: Decimal


class DashboardSummary(BaseModel):
    currency: str = "EUR"
    total_value_eur: Decimal
    by_source: list[AllocationItem]
    by_asset_type: list[AllocationItem]
    positions_count: int
    data_notice: str | None = None


class FeatureStatus(BaseModel):
    ai: bool
    news: bool
    benchmarks: bool

