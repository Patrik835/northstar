import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.enums import AssetType, Broker


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


class HoldingSource(BaseModel):
    broker: Broker
    connection_id: uuid.UUID
    provider_instrument_id: str
    provider_symbol: str
    provider_name: str | None
    canonical_instrument_id: uuid.UUID | None
    canonical_symbol: str
    canonical_name: str
    canonical_isin: str | None
    quantity: Decimal
    average_price: Decimal | None
    current_value: Decimal
    currency: str
    current_value_eur: Decimal
    reported_pnl: Decimal | None
    reported_pnl_eur: Decimal | None
    instrument_percentage: Decimal
    last_synced_at: datetime | None
    valued_at: datetime | None
    valuation_source: str
    is_estimated: bool
    freshness_status: Literal["fresh", "stale"]
    is_stale: bool


class Holding(BaseModel):
    key: str
    grouping: Literal["instrument", "company"]
    instrument_count: int
    canonical_instrument_id: uuid.UUID | None
    symbol: str
    symbols: list[str]
    name: str
    isin: str | None
    asset_type: AssetType
    total_quantity: Decimal | None
    total_value_eur: Decimal
    reported_pnl_eur: Decimal | None
    reported_pnl_source_count: int
    portfolio_percentage: Decimal
    source_count: int
    as_of: datetime | None
    is_stale: bool
    stale_source_count: int
    has_estimated_value: bool
    sources: list[HoldingSource]


class ReconciliationWarning(BaseModel):
    broker: Broker
    connection_id: uuid.UUID
    difference_percent: Decimal | None
    checked_at: datetime | None
    message: str


class HoldingsResponse(BaseModel):
    currency: str = "EUR"
    total_value_eur: Decimal
    reported_pnl_eur: Decimal | None
    reported_pnl_position_count: int
    instrument_count: int
    position_count: int
    unmatched_positions: int
    as_of: datetime | None
    stale_source_count: int
    estimated_position_count: int
    reconciliation_warnings: list[ReconciliationWarning]
    sources: list[AllocationItem]
    holdings: list[Holding]
