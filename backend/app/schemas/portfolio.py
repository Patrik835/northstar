import uuid
from datetime import datetime
from decimal import Decimal

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
    quantity: Decimal
    average_price: Decimal | None
    current_value: Decimal
    currency: str
    current_value_eur: Decimal
    reported_pnl: Decimal | None
    reported_pnl_eur: Decimal | None
    instrument_percentage: Decimal
    last_synced_at: datetime | None


class Holding(BaseModel):
    key: str
    canonical_instrument_id: uuid.UUID | None
    symbol: str
    name: str
    isin: str | None
    asset_type: AssetType
    total_quantity: Decimal
    total_value_eur: Decimal
    portfolio_percentage: Decimal
    source_count: int
    sources: list[HoldingSource]


class HoldingsResponse(BaseModel):
    currency: str = "EUR"
    total_value_eur: Decimal
    instrument_count: int
    position_count: int
    unmatched_positions: int
    sources: list[AllocationItem]
    holdings: list[Holding]
