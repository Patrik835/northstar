import json
import re
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import get_settings
from app.models.enums import AssetType, TransactionType
from app.repositories.portfolio import HoldingPositionRow, PortfolioRepository, TransactionRow
from app.schemas.portfolio import (
    AllocationItem,
    DashboardSummary,
    Holding,
    HoldingSource,
    HoldingsResponse,
    InvestmentPerformanceBreakdown,
    ReconciliationWarning,
)
from app.services.freshness import connection_freshness
from app.services.investment_ledger import AverageCostLedger, average_cost_ledger


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
    r"(?:\s+(?:incorporated|inc|corporation|corp|company|co|holding|holdings|"
    r"limited|ltd|plc|s\.a\.?|sa|a\.g\.?|ag|n\.v\.?|nv))+$",
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


def transaction_holding_key(row: TransactionRow) -> str | None:
    instrument = row.instrument
    if instrument is None:
        return None
    company = (
        company_identity(instrument.name)
        if instrument.asset_type is AssetType.STOCK
        else None
    )
    return f"company:{company[0]}" if company else str(instrument.id)


def _transaction_source_key(row: TransactionRow) -> str:
    return (
        str(row.instrument.id)
        if row.instrument is not None
        else f"raw:{row.transaction.ticker.casefold()}"
    )


def _position_source_key(row: HoldingPositionRow) -> str:
    instrument = row.instrument
    position = row.position
    return (
        str(instrument.id)
        if instrument is not None
        else f"raw:{position.ticker.casefold()}"
    )


def _open_pnl_percentage(value: Decimal | None, current_value: Decimal) -> Decimal | None:
    if value is None:
        return None
    cost = current_value - value
    if cost <= 0:
        return None
    return (value * 100 / cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _source_performance(
    *,
    asset_type: AssetType,
    current_value_eur: Decimal,
    reported_pnl_eur: Decimal | None,
    calculated: "CostResult",
    ledger: AverageCostLedger,
) -> InvestmentPerformanceBreakdown:
    if asset_type is AssetType.CASH:
        return InvestmentPerformanceBreakdown(
            income_eur=ledger.income_eur,
            fees_eur=ledger.fees_eur,
            missing_event_count=ledger.missing_event_count,
        )

    if reported_pnl_eur is not None:
        open_pnl = reported_pnl_eur
        open_source = "provider"
        implied_cost = current_value_eur - reported_pnl_eur
        cost_basis = implied_cost if implied_cost >= 0 else None
    elif calculated.coverage == "complete" and calculated.gain_eur is not None:
        open_pnl = calculated.gain_eur
        open_source = "calculated"
        cost_basis = calculated.cost_eur
    else:
        open_pnl = None
        open_source = "unavailable"
        cost_basis = None

    complete = (
        ledger.coverage == "complete"
        and ledger.missing_event_count == 0
        and open_pnl is not None
        and ledger.realized_pnl_eur is not None
    )
    has_data = any(
        (
            open_pnl is not None,
            ledger.trade_count > 0,
            ledger.income_eur != 0,
            ledger.fees_eur != 0,
        )
    )
    total_return = (
        ledger.realized_pnl_eur + open_pnl + ledger.income_eur - ledger.fees_eur
        if complete and open_pnl is not None and ledger.realized_pnl_eur is not None
        else None
    )
    return InvestmentPerformanceBreakdown(
        cost_basis_eur=cost_basis,
        open_pnl_eur=open_pnl,
        open_pnl_percentage=_open_pnl_percentage(open_pnl, current_value_eur),
        open_pnl_source=open_source,
        realized_pnl_eur=ledger.realized_pnl_eur,
        income_eur=ledger.income_eur,
        fees_eur=ledger.fees_eur,
        total_return_eur=total_return,
        coverage="complete" if complete else "partial" if has_data else "unavailable",
        missing_event_count=ledger.missing_event_count,
    )


def _combine_performance(
    breakdowns: list[InvestmentPerformanceBreakdown],
) -> InvestmentPerformanceBreakdown:
    if not breakdowns:
        return InvestmentPerformanceBreakdown()
    open_values = [item.open_pnl_eur for item in breakdowns if item.open_pnl_eur is not None]
    realized_values = [
        item.realized_pnl_eur for item in breakdowns if item.realized_pnl_eur is not None
    ]
    cost_values = [item.cost_basis_eur for item in breakdowns if item.cost_basis_eur is not None]
    complete = all(item.coverage == "complete" for item in breakdowns)
    open_complete = len(open_values) == len(breakdowns)
    realized_complete = len(realized_values) == len(breakdowns)
    sources = {
        item.open_pnl_source
        for item in breakdowns
        if item.open_pnl_source != "unavailable"
    }
    open_source = (
        next(iter(sources))
        if len(sources) == 1
        else "mixed" if sources else "unavailable"
    )
    open_pnl = sum(open_values, Decimal(0)) if open_values else None
    # With partial coverage this is a known subtotal, not a complete lifetime result.
    # The coverage flag lets clients label it accordingly; total_return remains withheld.
    realized = sum(realized_values, Decimal(0)) if realized_values else None
    income = sum((item.income_eur for item in breakdowns), Decimal(0))
    fees = sum((item.fees_eur for item in breakdowns), Decimal(0))
    cost = (
        sum(cost_values, Decimal(0))
        if len(cost_values) == len(breakdowns)
        else None
    )
    total_return = (
        realized + open_pnl + income - fees
        if complete
        and open_complete
        and realized_complete
        and realized is not None
        and open_pnl is not None
        else None
    )
    has_data = any(item.coverage != "unavailable" for item in breakdowns)
    return InvestmentPerformanceBreakdown(
        cost_basis_eur=cost,
        open_pnl_eur=open_pnl,
        open_pnl_percentage=(
            (open_pnl * 100 / cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if open_pnl is not None and cost is not None and cost > 0
            else None
        ),
        open_pnl_source=open_source,
        realized_pnl_eur=realized,
        income_eur=income,
        fees_eur=fees,
        total_return_eur=total_return,
        coverage="complete" if complete else "partial" if has_data else "unavailable",
        missing_event_count=sum(item.missing_event_count for item in breakdowns),
    )


def _closed_performance(ledger: AverageCostLedger) -> InvestmentPerformanceBreakdown:
    complete = ledger.coverage == "complete" and ledger.missing_event_count == 0
    has_data = any(
        (
            ledger.trade_count > 0,
            ledger.income_eur != 0,
            ledger.fees_eur != 0,
        )
    )
    realized = ledger.realized_pnl_eur
    return InvestmentPerformanceBreakdown(
        cost_basis_eur=Decimal(0) if complete else None,
        open_pnl_eur=Decimal(0) if complete else None,
        open_pnl_percentage=None,
        open_pnl_source="calculated" if complete else "unavailable",
        realized_pnl_eur=realized,
        income_eur=ledger.income_eur,
        fees_eur=ledger.fees_eur,
        total_return_eur=(
            realized + ledger.income_eur - ledger.fees_eur
            if complete and realized is not None
            else None
        ),
        coverage="complete" if complete else "partial" if has_data else "unavailable",
        missing_event_count=ledger.missing_event_count,
    )


@dataclass(frozen=True, slots=True)
class CostResult:
    cost_eur: Decimal | None
    gain_eur: Decimal | None
    gain_percentage: Decimal | None
    coverage: str


def _calculated_cost(
    rows: list[TransactionRow], current_quantity: Decimal, current_value_eur: Decimal
) -> CostResult:
    ledger = average_cost_ledger(rows, current_quantity)
    cost = ledger.cost_basis_eur
    if cost is None:
        return CostResult(None, None, None, ledger.coverage)
    if cost < 0 or current_quantity <= 0:
        return CostResult(None, None, None, "unavailable")
    gain = current_value_eur - cost
    gain_percentage = (
        (gain * 100 / cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cost
        else None
    )
    return CostResult(cost, gain, gain_percentage, "complete")


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
        transaction_loader = getattr(self.repository, "transaction_rows", None)
        transaction_rows = (
            await transaction_loader(user_id) if transaction_loader is not None else []
        )
        transactions_by_source: dict[tuple[uuid.UUID, str], list[TransactionRow]] = {}
        for transaction_row in transaction_rows:
            source_key = (
                transaction_row.connection_id,
                _transaction_source_key(transaction_row),
            )
            transactions_by_source.setdefault(source_key, []).append(transaction_row)
        current_quantities: dict[tuple[uuid.UUID, str], Decimal] = {}
        for position_row in rows:
            source_key = (
                position_row.connection_id,
                _position_source_key(position_row),
            )
            current_quantities[source_key] = (
                current_quantities.get(source_key, Decimal(0))
                + position_row.position.quantity
            )
        ledgers_by_source = {
            source_key: average_cost_ledger(
                source_transactions,
                current_quantities.get(source_key, Decimal(0)),
            )
            for source_key, source_transactions in transactions_by_source.items()
        }
        metadata_loader = getattr(self.repository, "holding_metadata", None)
        metadata_by_key = (
            await metadata_loader(user_id) if metadata_loader is not None else {}
        )
        total = sum((row.position.current_value_eur for row in rows), Decimal(0))
        reported_pnl_rows = [
            row.position.reported_pnl_eur
            for row in rows
            if row.position.reported_pnl_eur is not None
        ]
        canonical_groups: dict[str, list] = {}
        for row in rows:
            key = str(row.instrument.id) if row.instrument else f"unmatched:{row.position.id}"
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
                    row.instrument.canonical_symbol if row.instrument else row.position.ticker
                    for row in instrument_rows
                }
            )
            value = sum((row.position.current_value_eur for row in instrument_rows), Decimal(0))
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
                source_key = (row.connection_id, _position_source_key(row))
                relevant_transactions = transactions_by_source.get(source_key, [])
                ledger = ledgers_by_source.get(
                    source_key,
                    average_cost_ledger([], row.position.quantity),
                )
                calculated = _calculated_cost(
                    relevant_transactions,
                    row.position.quantity,
                    row.position.current_value_eur,
                )
                sources.append(
                    HoldingSource(
                        broker=row.broker,
                        connection_id=row.connection_id,
                        provider_instrument_id=row.position.instrument_id,
                        provider_symbol=row.position.ticker,
                        provider_name=row.position.name,
                        canonical_instrument_id=(row.instrument.id if row.instrument else None),
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
                        is_estimated=bool(getattr(row.position, "is_estimated", False)),
                        freshness_status="stale" if freshness.is_stale else "fresh",
                        is_stale=freshness.is_stale,
                        calculated_cost_eur=calculated.cost_eur,
                        calculated_gain_eur=calculated.gain_eur,
                        calculated_gain_percentage=calculated.gain_percentage,
                        gain_coverage=calculated.coverage,
                        performance=_source_performance(
                            asset_type=row.position.asset_type,
                            current_value_eur=row.position.current_value_eur,
                            reported_pnl_eur=row.position.reported_pnl_eur,
                            calculated=calculated,
                            ledger=ledger,
                        ),
                    )
                )
            holding_as_of = max(
                (source.valued_at for source in sources if source.valued_at is not None),
                default=None,
            )
            stale_connection_ids = {source.connection_id for source in sources if source.is_stale}
            calculated_sources = [
                source for source in sources if source.calculated_cost_eur is not None
            ]
            calculated_cost = (
                sum(
                    (
                        source.calculated_cost_eur or Decimal(0)
                        for source in calculated_sources
                    ),
                    Decimal(0),
                )
                if calculated_sources
                else None
            )
            calculated_gain = (
                value - calculated_cost if calculated_cost is not None else None
            )
            calculated_gain_percentage = (
                (calculated_gain * 100 / calculated_cost).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if calculated_cost and calculated_gain is not None
                else None
            )
            gain_coverage = (
                "complete"
                if calculated_sources
                and len(calculated_sources) == len(sources)
                and all(source.gain_coverage == "complete" for source in sources)
                else "partial" if calculated_sources else "unavailable"
            )
            holding_performance = _combine_performance(
                [
                    source.performance
                    for source in sources
                    if first.position.asset_type is not AssetType.CASH
                ]
            )
            metadata = metadata_by_key.get(key)
            try:
                tags = json.loads(metadata.tags_json) if metadata else []
            except (TypeError, ValueError):
                tags = []
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
                        else group_names.get(key) or first.position.name or first.position.ticker
                    ),
                    isin=instrument.isin if instrument else None,
                    asset_type=(instrument.asset_type if instrument else first.position.asset_type),
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
                        sum(instrument_pnl_rows, Decimal(0)) if instrument_pnl_rows else None
                    ),
                    reported_pnl_source_count=len(instrument_pnl_rows),
                    portfolio_percentage=percentage(value, total),
                    source_count=len(sources),
                    as_of=holding_as_of,
                    is_stale=bool(stale_connection_ids),
                    stale_source_count=len(stale_connection_ids),
                    has_estimated_value=any(source.is_estimated for source in sources),
                    sources=sources,
                    calculated_cost_eur=calculated_cost,
                    calculated_gain_eur=calculated_gain,
                    calculated_gain_percentage=calculated_gain_percentage,
                    gain_coverage=gain_coverage,
                    performance=holding_performance,
                    category=metadata.category if metadata else None,
                    tags=tags if isinstance(tags, list) else [],
                    notes=metadata.notes if metadata else None,
                    target_allocation_percentage=(
                        metadata.target_allocation_percentage if metadata else None
                    ),
                )
            )

        source_values: dict = {}
        for row in rows:
            source_values[row.broker] = (
                source_values.get(row.broker, Decimal(0)) + row.position.current_value_eur
            )
        all_sources = [source for holding in holdings for source in holding.sources]
        current_source_keys = set(current_quantities)
        closed_or_unattached_performance = [
            _closed_performance(ledger)
            for source_key, ledger in ledgers_by_source.items()
            if source_key not in current_source_keys
            and (
                ledger.trade_count > 0
                or ledger.income_eur != 0
                or ledger.fees_eur != 0
                or ledger.missing_event_count > 0
            )
        ]
        portfolio_performance = _combine_performance(
            [
                source.performance
                for source in all_sources
                if source.performance.open_pnl_eur is not None
                or source.performance.coverage != "unavailable"
            ]
            + closed_or_unattached_performance
        )
        external_flows = [
            item.transaction
            for item in transaction_rows
            if item.transaction.transaction_type
            in {TransactionType.DEPOSIT, TransactionType.WITHDRAWAL}
        ]
        valued_external_flows = [
            item for item in external_flows if item.value_eur is not None
        ]
        net_contributions = (
            sum(
                (
                    abs(item.value_eur)
                    if item.transaction_type is TransactionType.DEPOSIT
                    else -abs(item.value_eur)
                    for item in valued_external_flows
                    if item.value_eur is not None
                ),
                Decimal(0),
            )
            if valued_external_flows
            else None
        )
        external_flow_coverage = (
            "complete"
            if external_flows and len(valued_external_flows) == len(external_flows)
            else "partial" if valued_external_flows else "unavailable"
        )
        portfolio_as_of = max(
            (source.valued_at for source in all_sources if source.valued_at is not None),
            default=None,
        )
        stale_connection_ids = {source.connection_id for source in all_sources if source.is_stale}
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
            reported_pnl_eur=(sum(reported_pnl_rows, Decimal(0)) if reported_pnl_rows else None),
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
            performance=portfolio_performance,
            net_contributions_eur=net_contributions,
            external_flow_coverage=external_flow_coverage,
        )
