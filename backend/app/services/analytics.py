import math
import uuid
from bisect import bisect_right
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import pstdev

from app.models.enums import AssetType, TransactionType
from app.repositories.analytics import AnalyticsRepository
from app.repositories.portfolio import HoldingPositionRow, PortfolioRepository, TransactionRow
from app.schemas.analytics import (
    AllocationBreakdown,
    AnalyticsResponse,
    BenchmarkAnalytics,
    BenchmarkOption,
    BenchmarkPoint,
    PerformanceLeaders,
    Performer,
    RiskAnalytics,
    TargetAnalytics,
    TargetDriftItem,
)
from app.schemas.performance import PerformanceRange, PortfolioHistoryPoint
from app.schemas.portfolio import AllocationItem, HoldingsResponse
from app.services.instrument_classification import classify_instrument
from app.services.performance import PerformanceService
from app.services.portfolio import PortfolioService, percentage

CENT = Decimal("0.01")
SIX = Decimal("0.000001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _number(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _breakdown(
    dimension: str,
    values: dict[str, Decimal],
    scope: Decimal,
    *,
    covered: Decimal | None = None,
    message: str | None = None,
) -> AllocationBreakdown:
    known = scope if covered is None else covered
    items = [
        AllocationItem(label=label, value_eur=_money(value), percentage=percentage(value, scope))
        for label, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
        if value
    ]
    coverage = percentage(known, scope) if scope else Decimal(0)
    status = "available" if scope and known >= scope else "partial" if known else "unavailable"
    return AllocationBreakdown(
        dimension=dimension,  # type: ignore[arg-type]
        items=items,
        scope_value_eur=_money(scope),
        covered_value_eur=_money(known),
        coverage_percentage=coverage,
        status=status,
        message=message,
    )


def _growth_series(
    points: list[PortfolioHistoryPoint], external_flows: dict[date, Decimal]
) -> list[tuple[date, Decimal]]:
    if not points:
        return []
    initial = points[0].total_value_eur
    if initial <= 0:
        return []
    flow_dates = sorted(external_flows)
    flow_index = 0
    cumulative_flow = Decimal(0)
    result: list[tuple[date, Decimal]] = []
    for point in points:
        while flow_index < len(flow_dates) and flow_dates[flow_index] <= point.date:
            flow_date = flow_dates[flow_index]
            if flow_date > points[0].date:
                cumulative_flow += external_flows[flow_date]
            flow_index += 1
        contributed_capital = initial + cumulative_flow
        if contributed_capital <= 0:
            continue
        result.append((point.date, point.total_value_eur * 100 / contributed_capital))
    return result


class AnalyticsService:
    def __init__(
        self,
        portfolio_repository: PortfolioRepository,
        analytics_repository: AnalyticsRepository,
    ) -> None:
        self.portfolio_repository = portfolio_repository
        self.analytics_repository = analytics_repository

    async def get(self, user_id: uuid.UUID, selected_range: PerformanceRange) -> AnalyticsResponse:
        holdings = await PortfolioService(self.portfolio_repository).holdings(user_id)
        rows = await self.portfolio_repository.holding_positions(user_id)
        transactions = await self.portfolio_repository.transaction_rows(user_id)
        performance = await PerformanceService(self.portfolio_repository).portfolio(
            user_id, selected_range
        )
        usd_rates = await self.analytics_repository.usd_eur_rates(None, date.today())
        external_flows, missing_external_flows = self._external_flows(transactions, usd_rates)

        return AnalyticsResponse(
            range=selected_range,
            allocations=self._allocations(holdings, rows),
            performance=self._leaders(holdings),
            benchmark=await self._benchmark(
                user_id, performance, external_flows, missing_external_flows
            ),
            risk=self._risk(
                holdings,
                performance.points,
                performance.history_method,
                external_flows,
                missing_external_flows,
            ),
            targets=self._targets(holdings),
        )

    def _allocations(
        self,
        holdings: HoldingsResponse,
        rows: list[HoldingPositionRow],
    ) -> list[AllocationBreakdown]:
        total = holdings.total_value_eur
        asset_values: dict[str, Decimal] = defaultdict(Decimal)
        holding_values: dict[str, Decimal] = defaultdict(Decimal)
        broker_values: dict[str, Decimal] = defaultdict(Decimal)
        currency_values: dict[str, Decimal] = defaultdict(Decimal)
        for holding in holdings.holdings:
            asset_values[holding.asset_type.value] += holding.total_value_eur
            holding_values[f"{holding.symbol} · {holding.name}"] += holding.total_value_eur
        for row in rows:
            broker_values[row.broker.value] += row.position.current_value_eur
            currency_values[row.position.currency.upper()] += row.position.current_value_eur

        securities = [
            row
            for row in rows
            if (row.instrument.asset_type if row.instrument else row.position.asset_type)
            in {AssetType.STOCK, AssetType.ETF}
        ]
        scope = sum((row.position.current_value_eur for row in securities), Decimal(0))
        sectors: dict[str, Decimal] = defaultdict(Decimal)
        countries: dict[str, Decimal] = defaultdict(Decimal)
        sector_covered = Decimal(0)
        country_covered = Decimal(0)
        for row in securities:
            value = row.position.current_value_eur
            instrument = row.instrument
            if instrument is None:
                sectors["Unclassified"] += value
                countries["Unclassified"] += value
                continue
            classification = classify_instrument(instrument)
            if classification.sector:
                sectors[classification.sector] += value
                sector_covered += value
            else:
                sectors["Unclassified"] += value
            if classification.geography:
                countries[classification.geography] += value
                country_covered += value
            else:
                countries["Unclassified"] += value

        return [
            _breakdown("asset_type", asset_values, total),
            _breakdown("holding", holding_values, total),
            _breakdown("broker", broker_values, total),
            _breakdown("currency", currency_values, total),
            _breakdown(
                "sector",
                sectors,
                scope,
                covered=sector_covered,
                message=(
                    "Verified metadata is preferred; conservative symbol and descriptive "
                    "classification rules fill known gaps."
                ),
            ),
            _breakdown(
                "geography",
                countries,
                scope,
                covered=country_covered,
                message=(
                    "Verified geography is preferred; canonical mappings and ISIN country "
                    "codes fill known gaps."
                ),
            ),
        ]

    @staticmethod
    def _leaders(holdings: HoldingsResponse) -> PerformanceLeaders:
        investable_total = sum(
            (
                holding.total_value_eur
                for holding in holdings.holdings
                if holding.asset_type is not AssetType.CASH
            ),
            Decimal(0),
        )
        covered = Decimal(0)
        performers: list[Performer] = []
        for holding in holdings.holdings:
            pnl = holding.performance.open_pnl_eur
            pnl_percentage = holding.performance.open_pnl_percentage
            source = holding.performance.open_pnl_source
            if pnl is None or pnl_percentage is None or source == "unavailable":
                continue
            covered += holding.total_value_eur
            performers.append(
                Performer(
                    holding_key=holding.key,
                    symbol=holding.symbol,
                    name=holding.name,
                    current_value_eur=holding.total_value_eur,
                    open_pnl_eur=pnl,
                    open_pnl_percentage=pnl_percentage,
                    contribution_percentage_points=(
                        _number(pnl * 100 / investable_total) if investable_total else Decimal(0)
                    ),
                    source=source,  # type: ignore[arg-type]
                )
            )
        return PerformanceLeaders(
            best=sorted(performers, key=lambda item: item.open_pnl_percentage, reverse=True)[:5],
            worst=sorted(performers, key=lambda item: item.open_pnl_percentage)[:5],
            contributors=sorted(
                performers, key=lambda item: abs(item.contribution_percentage_points), reverse=True
            )[:8],
            coverage_percentage=percentage(covered, investable_total),
            message=(
                "Based on current open P/L; contribution is the impact on current portfolio value."
            ),
        )

    @staticmethod
    def _external_flows(
        transactions: list[TransactionRow], usd_rates: list
    ) -> tuple[dict[date, Decimal], int]:
        rate_dates = [row.rate_date for row in usd_rates]
        rates = {row.rate_date: row.rate for row in usd_rates}
        flows: dict[date, Decimal] = defaultdict(Decimal)
        missing = 0
        for row in transactions:
            item = row.transaction
            if item.transaction_type not in {
                TransactionType.DEPOSIT,
                TransactionType.WITHDRAWAL,
            }:
                continue
            value = abs(item.value_eur) if item.value_eur is not None else None
            if value is None and item.currency.upper() == "EUR":
                value = abs(item.value)
            if value is None and item.currency.upper() == "USD" and rate_dates:
                position = bisect_right(rate_dates, item.executed_at.date()) - 1
                if position >= 0:
                    value = abs(item.value) * rates[rate_dates[position]]
            if value is None:
                missing += 1
                continue
            direction = (
                Decimal(1) if item.transaction_type is TransactionType.DEPOSIT else Decimal(-1)
            )
            flows[item.executed_at.date()] += value * direction
        return dict(flows), missing

    async def _benchmark(
        self,
        user_id: uuid.UUID,
        performance,
        external_flows: dict[date, Decimal],
        missing_external_flows: int,
    ) -> BenchmarkAnalytics:
        options = await self.analytics_repository.benchmark_options()
        option_models = [
            BenchmarkOption(
                instrument_id=item.id,
                symbol=item.canonical_symbol,
                name=item.name,
            )
            for item in options
        ]
        if not options or not performance.points or performance.end_date is None:
            return BenchmarkAnalytics(
                selected_instrument_id=None,
                selected_symbol=None,
                selected_name=None,
                options=option_models,
                points=[],
                portfolio_return_percentage=None,
                benchmark_return_percentage=None,
                relative_return_percentage=None,
                status="unavailable",
                message="A cached ETF price series is required for comparison.",
            )
        profile = await self.analytics_repository.profile(user_id)
        selected = next(
            (item for item in options if profile and item.id == profile.benchmark_instrument_id),
            None,
        )
        if selected is None:
            selected = next(
                (item for item in options if item.canonical_symbol == "SPY5.L"), options[0]
            )
        prices = await self.analytics_repository.benchmark_prices(
            selected.id, performance.start_date, performance.end_date
        )
        rates = await self.analytics_repository.usd_eur_rates(
            performance.start_date, performance.end_date
        )
        rate_dates = [row.rate_date for row in rates]
        rate_values = {row.rate_date: row.rate for row in rates}
        price_dates: list[date] = []
        price_values: list[Decimal] = []
        for price in prices:
            value = price.close_price
            if price.currency == "USD":
                rate_position = bisect_right(rate_dates, price.price_date) - 1
                if rate_position < 0:
                    continue
                value *= rate_values[rate_dates[rate_position]]
            elif price.currency != "EUR":
                continue
            price_dates.append(price.price_date)
            price_values.append(value)
        growth = _growth_series(performance.points, external_flows)
        if not price_dates or len(growth) < 2:
            return BenchmarkAnalytics(
                selected_instrument_id=selected.id,
                selected_symbol=selected.canonical_symbol,
                selected_name=selected.name,
                options=option_models,
                points=[],
                portfolio_return_percentage=None,
                benchmark_return_percentage=None,
                relative_return_percentage=None,
                status="unavailable",
                message="The selected ETF has no overlapping cached history for this range.",
            )
        aligned: list[tuple[date, Decimal, Decimal]] = []
        for point_date, portfolio_index in growth:
            position = bisect_right(price_dates, point_date) - 1
            if position >= 0:
                aligned.append((point_date, portfolio_index, price_values[position]))
        if len(aligned) < 2 or aligned[0][1] <= 0 or aligned[0][2] <= 0:
            return BenchmarkAnalytics(
                selected_instrument_id=selected.id,
                selected_symbol=selected.canonical_symbol,
                selected_name=selected.name,
                options=option_models,
                points=[],
                portfolio_return_percentage=None,
                benchmark_return_percentage=None,
                relative_return_percentage=None,
                status="unavailable",
                message="At least two overlapping portfolio and benchmark observations are needed.",
            )
        first_portfolio = aligned[0][1]
        first_benchmark = aligned[0][2]
        initial_value = performance.points[0].total_value_eur
        units = initial_value / first_benchmark
        cumulative_flow = Decimal(0)
        flow_dates = sorted(external_flows)
        flow_index = 0
        points: list[BenchmarkPoint] = []
        for point_date, portfolio_index, benchmark_value in aligned:
            while flow_index < len(flow_dates) and flow_dates[flow_index] <= point_date:
                flow_date = flow_dates[flow_index]
                if flow_date > aligned[0][0]:
                    flow = external_flows[flow_date]
                    price_position = bisect_right(price_dates, flow_date) - 1
                    if price_position >= 0 and price_values[price_position] > 0:
                        units += flow / price_values[price_position]
                        cumulative_flow += flow
                flow_index += 1
            contributed_capital = initial_value + cumulative_flow
            if contributed_capital <= 0:
                continue
            benchmark_index = units * benchmark_value * 100 / contributed_capital
            points.append(
                BenchmarkPoint(
                    date=point_date.isoformat(),
                    portfolio_return_percentage=_number(
                        portfolio_index / first_portfolio * 100 - 100
                    ),
                    benchmark_return_percentage=_number(benchmark_index - 100),
                )
            )
        portfolio_return = points[-1].portfolio_return_percentage
        benchmark_return = points[-1].benchmark_return_percentage
        return BenchmarkAnalytics(
            selected_instrument_id=selected.id,
            selected_symbol=selected.canonical_symbol,
            selected_name=selected.name,
            options=option_models,
            points=points,
            portfolio_return_percentage=portfolio_return,
            benchmark_return_percentage=benchmark_return,
            relative_return_percentage=_number(portfolio_return - benchmark_return),
            status=(
                "partial"
                if performance.history_method == "reconstructed" or missing_external_flows
                else "available"
            ),
            message=(
                "Portfolio and ETF comparison uses the same starting value and imported net "
                "cash flows. Reconstructed history or missing transfers makes it an estimate."
            ),
        )

    @staticmethod
    def _risk(
        holdings: HoldingsResponse,
        points: list[PortfolioHistoryPoint],
        history_method: str,
        external_flows: dict[date, Decimal],
        missing_external_flows: int,
    ) -> RiskAnalytics:
        investable = [item for item in holdings.holdings if item.asset_type is not AssetType.CASH]
        total = sum((item.total_value_eur for item in investable), Decimal(0))
        weights = [item.total_value_eur / total for item in investable] if total else []
        hhi = sum((weight * weight for weight in weights), Decimal(0))
        effective = Decimal(1) / hhi if hhi else Decimal(0)
        count = len(weights)
        diversification = (
            (Decimal(1) - hhi) / (Decimal(1) - Decimal(1) / count) * 100
            if count > 1
            else Decimal(0)
        )
        growth = _growth_series(points, external_flows)
        returns = [
            float(current / previous - 1)
            for (_, previous), (_, current) in zip(growth, growth[1:], strict=False)
            if previous > 0
        ]
        maximum_drawdown: Decimal | None = None
        if growth:
            peak = growth[0][1]
            worst = Decimal(0)
            for _, value in growth:
                peak = max(peak, value)
                if peak:
                    worst = min(worst, value / peak - 1)
            maximum_drawdown = _number(abs(worst) * 100)
        volatility: Decimal | None = None
        if len(returns) >= 2:
            intervals = [
                (current[0] - previous[0]).days
                for previous, current in zip(growth, growth[1:], strict=False)
                if current[0] > previous[0]
            ]
            average_days = sum(intervals) / len(intervals) if intervals else 7
            volatility = _number(
                Decimal(str(pstdev(returns) * math.sqrt(365 / average_days) * 100))
            )
        return RiskAnalytics(
            maximum_drawdown_percentage=maximum_drawdown,
            annualized_volatility_percentage=volatility,
            largest_holding_percentage=_number(max(weights, default=Decimal(0)) * 100),
            top_five_percentage=_number(sum(sorted(weights, reverse=True)[:5], Decimal(0)) * 100),
            concentration_hhi=hhi.quantize(SIX),
            effective_holdings=effective.quantize(Decimal("0.1")),
            diversification_score=_number(max(Decimal(0), min(Decimal(100), diversification))),
            observation_count=len(growth),
            status=(
                "unavailable"
                if len(growth) < 2
                else "partial"
                if history_method == "reconstructed" or missing_external_flows
                else "available"
            ),
            message=(
                "Return risk uses cash-flow-adjusted chart observations; reconstructed history "
                "makes drawdown and volatility estimates. Concentration uses current holdings."
            ),
        )

    @staticmethod
    def _targets(holdings: HoldingsResponse) -> TargetAnalytics:
        items: list[TargetDriftItem] = []
        total_target = Decimal(0)
        for holding in holdings.holdings:
            if holding.asset_type is AssetType.CASH:
                continue
            target = holding.target_allocation_percentage
            if target is not None:
                total_target += target
                drift = holding.portfolio_percentage - target
                target_value = holdings.total_value_eur * target / 100
                difference = target_value - holding.total_value_eur
                action = (
                    "on_target"
                    if abs(drift) < Decimal("0.5")
                    else "add"
                    if difference > 0
                    else "reduce"
                )
            else:
                drift = None
                target_value = None
                difference = None
                action = "not_set"
            items.append(
                TargetDriftItem(
                    holding_key=holding.key,
                    symbol=holding.symbol,
                    name=holding.name,
                    current_percentage=holding.portfolio_percentage,
                    target_percentage=target,
                    drift_percentage_points=drift,
                    current_value_eur=holding.total_value_eur,
                    target_value_eur=_money(target_value) if target_value is not None else None,
                    difference_eur=_money(difference) if difference is not None else None,
                    action=action,  # type: ignore[arg-type]
                )
            )
        return TargetAnalytics(
            target_total_percentage=_number(total_target),
            unallocated_percentage=_number(max(Decimal(0), Decimal(100) - total_target)),
            items=items,
            message=(
                "Educational illustration using current portfolio value only. It ignores taxes, "
                "fees, liquidity, account constraints, and personal suitability."
            ),
        )
