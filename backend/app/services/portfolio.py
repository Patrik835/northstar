import re
import uuid
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import get_settings
from app.models.enums import AssetType
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import (
    AllocationItem,
    DashboardSummary,
    Holding,
    HoldingSource,
    HoldingsResponse,
    ReconciliationWarning,
)
from app.services.freshness import connection_freshness


def percentage(value: Decimal, total: Decimal) -> Decimal:
    if not total:
        return Decimal("0")
    return (value * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


SHARE_CLASS_SUFFIX = re.compile(
    r"(?:\s*\((?:class|series)\s+[a-z0-9.-]+\)|"
    r"\s+(?:class|series)\s+[a-z0-9.-]+(?:\s+shares?)?)$",
    re.IGNORECASE,
)
LEGAL_SUFFIX = re.compile(
    r"\s+(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|"
    r"s\.a\.?|sa|a\.g\.?|ag|n\.v\.?|nv)$",
    re.IGNORECASE,
)


def company_identity(name: str) -> tuple[str, str] | None:
    """Return a conservative issuer key for grouping listed stock classes.

    Canonical instruments remain distinct securities. This key only groups their
    portfolio presentation when broker names differ by share class/legal suffix.
    """

    display_name = SHARE_CLASS_SUFFIX.sub("", name.strip()).strip(" ,-.")
    comparable_name = LEGAL_SUFFIX.sub("", display_name).strip(" ,-.")
    key = re.sub(r"[^a-z0-9]+", " ", comparable_name.casefold()).strip()
    if len(key) < 3:
        return None
    return key, display_name


class PortfolioService:
    def __init__(
        self,
        repository: PortfolioRepository,
        sync_interval_minutes: int | None = None,
    ) -> None:
        self.repository = repository
        self.sync_interval_minutes = (
            sync_interval_minutes
            if sync_interval_minutes is not None
            else get_settings().portfolio_sync_minutes
        )

    async def dashboard(self, user_id: uuid.UUID) -> DashboardSummary:
        total = await self.repository.total(user_id)
        source_rows = await self.repository.by_source(user_id)
        asset_rows = await self.repository.by_asset_type(user_id)
        return DashboardSummary(
            total_value_eur=total,
            positions_count=await self.repository.position_count(user_id),
            by_source=[
                AllocationItem(
                    label=label.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for label, value in source_rows
            ],
            by_asset_type=[
                AllocationItem(
                    label=label.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for label, value in asset_rows
            ],
            data_notice="History begins when each live connection is first synchronized.",
        )

    async def holdings(self, user_id: uuid.UUID) -> HoldingsResponse:
        rows = await self.repository.holding_positions(user_id)
        quality_rows = await self.repository.connection_quality(user_id)
        total = sum((row.position.current_value_eur for row in rows), Decimal(0))
        reported_pnl_rows = [
            row.position.reported_pnl_eur
            for row in rows
            if row.position.reported_pnl_eur is not None
        ]
        canonical_groups: dict[str, list] = {}
        for row in rows:
            key = (
                str(row.instrument.id)
                if row.instrument
                else f"unmatched:{row.position.id}"
            )
            canonical_groups.setdefault(key, []).append(row)

        grouped: dict[str, list] = {}
        group_names: dict[str, str] = {}
        for canonical_key, instrument_rows in canonical_groups.items():
            instrument = instrument_rows[0].instrument
            company = (
                company_identity(instrument.name)
                if instrument and instrument.asset_type is AssetType.STOCK
                else None
            )
            key = f"company:{company[0]}" if company else canonical_key
            grouped.setdefault(key, []).extend(instrument_rows)
            if company:
                current_name = group_names.get(key)
                if current_name is None or len(company[1]) < len(current_name):
                    group_names[key] = company[1]

        holdings: list[Holding] = []
        for key, instrument_rows in grouped.items():
            first = instrument_rows[0]
            instruments = {
                row.instrument.id: row.instrument
                for row in instrument_rows
                if row.instrument is not None
            }
            instrument = next(iter(instruments.values())) if len(instruments) == 1 else None
            is_company_group = len(instruments) > 1
            symbols = sorted(
                {
                    row.instrument.canonical_symbol
                    if row.instrument
                    else row.position.ticker
                    for row in instrument_rows
                }
            )
            value = sum(
                (row.position.current_value_eur for row in instrument_rows), Decimal(0)
            )
            instrument_pnl_rows = [
                row.position.reported_pnl_eur
                for row in instrument_rows
                if row.position.reported_pnl_eur is not None
            ]
            sources: list[HoldingSource] = []
            for row in sorted(instrument_rows, key=lambda item: item.broker.value):
                freshness = connection_freshness(
                    row.broker, row.last_synced_at, self.sync_interval_minutes
                )
                valued_at = getattr(row.position, "valued_at", None) or row.last_synced_at
                sources.append(
                    HoldingSource(
                    broker=row.broker,
                    connection_id=row.connection_id,
                    provider_instrument_id=row.position.instrument_id,
                    provider_symbol=row.position.ticker,
                    provider_name=row.position.name,
                    canonical_instrument_id=(
                        row.instrument.id if row.instrument else None
                    ),
                    canonical_symbol=(
                        row.instrument.canonical_symbol
                        if row.instrument
                        else row.position.ticker
                    ),
                    canonical_name=(
                        row.instrument.name
                        if row.instrument
                        else row.position.name or row.position.ticker
                    ),
                    canonical_isin=row.instrument.isin if row.instrument else None,
                    quantity=row.position.quantity,
                    average_price=row.position.average_price,
                    current_value=row.position.current_value,
                    currency=row.position.currency,
                    current_value_eur=row.position.current_value_eur,
                    reported_pnl=row.position.reported_pnl,
                    reported_pnl_eur=row.position.reported_pnl_eur,
                    instrument_percentage=percentage(row.position.current_value_eur, value),
                    last_synced_at=row.last_synced_at,
                    valued_at=valued_at,
                    valuation_source=(
                        getattr(row.position, "valuation_source", None) or "provider"
                    ),
                    is_estimated=bool(
                        getattr(row.position, "is_estimated", False)
                    ),
                    freshness_status="stale" if freshness.is_stale else "fresh",
                    is_stale=freshness.is_stale,
                    )
                )
            holding_as_of = max(
                (source.valued_at for source in sources if source.valued_at is not None),
                default=None,
            )
            stale_connection_ids = {
                source.connection_id for source in sources if source.is_stale
            }
            holdings.append(
                Holding(
                    key=key,
                    grouping="company" if is_company_group else "instrument",
                    instrument_count=max(len(instruments), 1),
                    canonical_instrument_id=instrument.id if instrument else None,
                    symbol=(instrument.canonical_symbol if instrument else " / ".join(symbols)),
                    symbols=symbols,
                    name=(
                        instrument.name
                        if instrument
                        else group_names.get(key)
                        or first.position.name
                        or first.position.ticker
                    ),
                    isin=instrument.isin if instrument else None,
                    asset_type=(
                        instrument.asset_type if instrument else first.position.asset_type
                    ),
                    total_quantity=(
                        sum(
                            (row.position.quantity for row in instrument_rows),
                            Decimal(0),
                        )
                        if not is_company_group
                        else None
                    ),
                    total_value_eur=value,
                    reported_pnl_eur=(
                        sum(instrument_pnl_rows, Decimal(0))
                        if instrument_pnl_rows
                        else None
                    ),
                    reported_pnl_source_count=len(instrument_pnl_rows),
                    portfolio_percentage=percentage(value, total),
                    source_count=len(sources),
                    as_of=holding_as_of,
                    is_stale=bool(stale_connection_ids),
                    stale_source_count=len(stale_connection_ids),
                    has_estimated_value=any(source.is_estimated for source in sources),
                    sources=sources,
                )
            )

        source_values: dict = {}
        for row in rows:
            source_values[row.broker] = (
                source_values.get(row.broker, Decimal(0))
                + row.position.current_value_eur
            )
        all_sources = [source for holding in holdings for source in holding.sources]
        portfolio_as_of = max(
            (source.valued_at for source in all_sources if source.valued_at is not None),
            default=None,
        )
        stale_connection_ids = {
            source.connection_id for source in all_sources if source.is_stale
        }
        reconciliation_warnings: dict[uuid.UUID, ReconciliationWarning] = {}
        for quality in quality_rows:
            if quality.reconciliation_warning:
                reconciliation_warnings[quality.connection_id] = ReconciliationWarning(
                    broker=quality.broker,
                    connection_id=quality.connection_id,
                    difference_percent=quality.reconciliation_difference_percent,
                    checked_at=quality.reconciliation_checked_at,
                    message=quality.reconciliation_warning,
                )
        return HoldingsResponse(
            total_value_eur=total,
            reported_pnl_eur=(
                sum(reported_pnl_rows, Decimal(0)) if reported_pnl_rows else None
            ),
            reported_pnl_position_count=len(reported_pnl_rows),
            instrument_count=len(holdings),
            position_count=len(rows),
            unmatched_positions=sum(row.instrument is None for row in rows),
            as_of=portfolio_as_of,
            stale_source_count=len(stale_connection_ids),
            estimated_position_count=sum(source.is_estimated for source in all_sources),
            reconciliation_warnings=list(reconciliation_warnings.values()),
            sources=[
                AllocationItem(
                    label=broker.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for broker, value in sorted(
                    source_values.items(), key=lambda item: item[1], reverse=True
                )
            ],
            holdings=sorted(holdings, key=lambda item: item.total_value_eur, reverse=True),
        )
