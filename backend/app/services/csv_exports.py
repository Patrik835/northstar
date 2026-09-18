import csv
import io
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from app.integrations.market_data import EcbFxRateProvider
from app.models.enums import AssetType, Broker, TransactionType
from app.repositories.portfolio import PortfolioRepository
from app.schemas.activity import ActivityResponse
from app.schemas.performance import PerformanceRange, PortfolioPerformanceResponse
from app.schemas.portfolio import Holding, HoldingSource, HoldingsResponse
from app.services.activity import ActivityService
from app.services.performance import PerformanceService
from app.services.portfolio import PortfolioService

AssetGroup = Literal["all", "equities", "crypto", "other"]


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    # Prevent spreadsheet applications from executing imported text as a formula.
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def csv_document(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(_csv_cell(value) for value in row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _in_asset_group(asset_type: AssetType, asset_group: AssetGroup) -> bool:
    if asset_group == "all":
        return True
    if asset_group == "equities":
        return asset_type in {AssetType.STOCK, AssetType.ETF}
    if asset_group == "crypto":
        return asset_type is AssetType.CRYPTO
    return asset_type in {AssetType.CASH, AssetType.OTHER}


def _matches_holding(holding: Holding, sources: list[HoldingSource], search: str | None) -> bool:
    query = (search or "").strip().casefold()
    if not query:
        return True
    values = [
        holding.symbol,
        holding.name,
        holding.isin or "",
        *holding.symbols,
        *(
            value
            for source in sources
            for value in (
                source.provider_symbol,
                source.provider_name or "",
                source.canonical_symbol,
                source.canonical_name,
                source.canonical_isin or "",
            )
        ),
    ]
    return any(query in value.casefold() for value in values)


def _sum_available(values: Iterable[Decimal | None]) -> Decimal | None:
    available = [value for value in values if value is not None]
    return sum(available, Decimal(0)) if available else None


def holdings_csv(
    portfolio: HoldingsResponse,
    *,
    broker: Broker | None = None,
    asset_group: AssetGroup = "all",
    search: str | None = None,
) -> bytes:
    selected: list[tuple[Holding, list[HoldingSource]]] = []
    for holding in portfolio.holdings:
        if not _in_asset_group(holding.asset_type, asset_group):
            continue
        sources = [
            source for source in holding.sources if broker is None or source.broker is broker
        ]
        if sources and _matches_holding(holding, sources, search):
            selected.append((holding, sources))
    selected_total = sum(
        (source.current_value_eur for _, sources in selected for source in sources),
        Decimal(0),
    )

    rows: list[list[object]] = []
    for holding, sources in selected:
        value = sum((source.current_value_eur for source in sources), Decimal(0))
        instrument_ids = {
            source.canonical_instrument_id or source.provider_instrument_id for source in sources
        }
        quantity = (
            sum((source.quantity for source in sources), Decimal(0))
            if len(instrument_ids) == 1
            else None
        )
        open_pnl_values = [source.performance.open_pnl_eur for source in sources]
        open_pnl = _sum_available(open_pnl_values)
        open_pnl_coverage = (
            "complete"
            if open_pnl is not None and all(item is not None for item in open_pnl_values)
            else "partial"
            if open_pnl is not None
            else "unavailable"
        )
        open_cost = value - open_pnl if open_pnl is not None else None
        open_pnl_percentage = (
            open_pnl * 100 / open_cost
            if open_pnl is not None and open_cost is not None and open_cost > 0
            else None
        )
        cost_values = [source.performance.cost_basis_eur for source in sources]
        cost_basis = (
            sum((item for item in cost_values if item is not None), Decimal(0))
            if all(item is not None for item in cost_values)
            else None
        )
        realized = _sum_available(source.performance.realized_pnl_eur for source in sources)
        income = sum((source.performance.income_eur for source in sources), Decimal(0))
        fees = sum((source.performance.fees_eur for source in sources), Decimal(0))
        total_return_values = [source.performance.total_return_eur for source in sources]
        total_return = (
            sum((item for item in total_return_values if item is not None), Decimal(0))
            if all(item is not None for item in total_return_values)
            else None
        )
        rows.append(
            [
                holding.key,
                holding.symbol,
                holding.name,
                holding.isin,
                holding.asset_type.value,
                quantity,
                value,
                value * 100 / selected_total if selected_total else Decimal(0),
                cost_basis,
                open_pnl,
                open_pnl_percentage,
                open_pnl_coverage,
                realized,
                income,
                fees,
                total_return,
                len(sources),
                "; ".join(sorted({source.broker.value for source in sources})),
                "; ".join(sorted({source.provider_symbol for source in sources})),
                max((source.valued_at for source in sources if source.valued_at), default=None),
                any(source.is_stale for source in sources),
                any(source.is_estimated for source in sources),
                holding.category,
                "; ".join(holding.tags),
                holding.notes,
                holding.target_allocation_percentage,
            ]
        )
    rows.sort(key=lambda row: Decimal(str(row[6])), reverse=True)
    return csv_document(
        [
            "holding_key",
            "symbol",
            "name",
            "isin",
            "asset_type",
            "quantity",
            "value_eur",
            "portfolio_percentage",
            "cost_basis_eur",
            "open_pnl_eur",
            "open_pnl_percentage",
            "open_pnl_coverage",
            "realized_pnl_eur",
            "income_eur",
            "fees_eur",
            "total_return_eur",
            "source_count",
            "sources",
            "provider_symbols",
            "valued_at_utc",
            "is_stale",
            "is_estimated",
            "category",
            "tags",
            "notes",
            "target_allocation_percentage",
        ],
        rows,
    )


def transactions_csv(activity: ActivityResponse) -> bytes:
    return csv_document(
        [
            "transaction_id",
            "executed_at_utc",
            "transaction_type",
            "symbol",
            "name",
            "source",
            "quantity",
            "price",
            "native_value",
            "native_currency",
            "value_eur",
            "fx_status",
            "holding_key",
            "connection_id",
        ],
        (
            [
                item.id,
                item.executed_at,
                item.transaction_type.value,
                item.symbol,
                item.name,
                item.broker.value,
                item.quantity,
                item.price,
                item.value,
                item.currency,
                item.value_eur,
                (
                    "unavailable"
                    if item.value_eur is None
                    else "estimated"
                    if item.is_estimated_fx
                    else "stored_or_exact"
                ),
                item.holding_key,
                item.connection_id,
            ]
            for item in activity.items
        ),
    )


def income_csv(activity: ActivityResponse) -> bytes:
    return csv_document(
        [
            "transaction_id",
            "paid_at_utc",
            "symbol",
            "name",
            "source",
            "quantity",
            "native_value",
            "native_currency",
            "value_eur",
            "fx_status",
            "holding_key",
            "connection_id",
        ],
        (
            [
                item.id,
                item.executed_at,
                item.symbol,
                item.name,
                item.broker.value,
                item.quantity,
                item.value,
                item.currency,
                item.value_eur,
                (
                    "unavailable"
                    if item.value_eur is None
                    else "estimated"
                    if item.is_estimated_fx
                    else "stored_or_exact"
                ),
                item.holding_key,
                item.connection_id,
            ]
            for item in activity.items
            if item.transaction_type is TransactionType.DIVIDEND
        ),
    )


def performance_csv(performance: PortfolioPerformanceResponse) -> bytes:
    points = performance.points or [None]
    return csv_document(
        [
            "date",
            "total_value_eur",
            "net_invested_eur",
            "invested_value_eur",
            "range",
            "history_method",
            "sampling",
            "money_weighted_return_percentage",
            "money_weighted_return_status",
            "time_weighted_return_percentage",
            "time_weighted_return_status",
            "total_return_eur",
            "capital_gain_eur",
            "income_eur",
            "fees_eur",
            "currency_movement_eur",
            "attribution_status",
        ],
        (
            [
                point.date if point else None,
                point.total_value_eur if point else None,
                point.net_invested_eur if point else None,
                point.invested_value_eur if point else None,
                performance.range,
                performance.history_method,
                performance.sampling,
                performance.money_weighted_return.percentage,
                performance.money_weighted_return.status,
                performance.time_weighted_return.percentage,
                performance.time_weighted_return.status,
                performance.attribution.total_return_eur,
                performance.attribution.capital_gain_eur,
                performance.attribution.income_eur,
                performance.attribution.fees_eur,
                performance.attribution.currency_movement_eur,
                performance.attribution.status,
            ]
            for point in points
        ),
    )


class CsvExportService:
    def __init__(self, repository: PortfolioRepository) -> None:
        self.repository = repository

    async def holdings(
        self,
        user_id: uuid.UUID,
        *,
        broker: Broker | None,
        asset_group: AssetGroup,
        search: str | None,
    ) -> bytes:
        portfolio = await PortfolioService(self.repository).holdings(user_id)
        return holdings_csv(portfolio, broker=broker, asset_group=asset_group, search=search)

    async def activity(
        self,
        user_id: uuid.UUID,
        *,
        broker: Broker | None,
        transaction_type: TransactionType | None,
        activity_group: Literal["trade", "dividend", "deposit"] | None,
        date_from: date | None,
        date_to: date | None,
        search: str | None,
    ) -> bytes:
        result = await ActivityService(
            self.repository,
            fx_rates=EcbFxRateProvider(self.repository.db),
        ).list(
            user_id,
            broker=broker,
            transaction_type=transaction_type,
            activity_group=activity_group,
            date_from=date_from,
            date_to=date_to,
            search=search,
            offset=0,
            limit=10_000_000,
        )
        return transactions_csv(result)

    async def income(
        self,
        user_id: uuid.UUID,
        *,
        broker: Broker | None,
        date_from: date | None,
        date_to: date | None,
        search: str | None,
    ) -> bytes:
        result = await ActivityService(
            self.repository,
            fx_rates=EcbFxRateProvider(self.repository.db),
        ).list(
            user_id,
            broker=broker,
            activity_group="dividend",
            date_from=date_from,
            date_to=date_to,
            search=search,
            offset=0,
            limit=10_000_000,
        )
        return income_csv(result)

    async def performance(self, user_id: uuid.UUID, selected_range: PerformanceRange) -> bytes:
        result = await PerformanceService(self.repository).portfolio(user_id, selected_range)
        return performance_csv(result)
