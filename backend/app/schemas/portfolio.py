import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class InvestmentPerformanceBreakdown(BaseModel):
    cost_basis_eur: Decimal | None = None
    open_pnl_eur: Decimal | None = None
    open_pnl_percentage: Decimal | None = None
    open_pnl_source: Literal[
        "provider", "calculated", "mixed", "unavailable"
    ] = "unavailable"
    realized_pnl_eur: Decimal | None = None
    income_eur: Decimal = Decimal(0)
    fees_eur: Decimal = Decimal(0)
    total_return_eur: Decimal | None = None
    coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    missing_event_count: int = 0


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
    calculated_cost_eur: Decimal | None = None
    calculated_gain_eur: Decimal | None = None
    calculated_gain_percentage: Decimal | None = None
    gain_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    performance: InvestmentPerformanceBreakdown = Field(
        default_factory=InvestmentPerformanceBreakdown
    )


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
    calculated_cost_eur: Decimal | None = None
    calculated_gain_eur: Decimal | None = None
    calculated_gain_percentage: Decimal | None = None
    gain_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    performance: InvestmentPerformanceBreakdown = Field(
        default_factory=InvestmentPerformanceBreakdown
    )
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    target_allocation_percentage: Decimal | None = None


class HoldingMetadataUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=12)
    notes: str | None = Field(default=None, max_length=2000)
    target_allocation_percentage: Decimal | None = Field(default=None, ge=0, le=100)

    @field_validator("category", "notes")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for raw in value:
            tag = raw.strip()[:32]
            if tag and tag.casefold() not in {item.casefold() for item in result}:
                result.append(tag)
        return result


class HoldingMetadataRead(HoldingMetadataUpdate):
    holding_key: str
    updated_at: datetime | None = None


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
    performance: InvestmentPerformanceBreakdown = Field(
        default_factory=InvestmentPerformanceBreakdown
    )
    net_contributions_eur: Decimal | None = None
    external_flow_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
