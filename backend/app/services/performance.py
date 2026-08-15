import math
import uuid
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.models.enums import TransactionType
from app.repositories.portfolio import (
    HistoricalPriceRow,
    PortfolioRepository,
    SnapshotRow,
    TransactionRow,
)
from app.schemas.performance import (
    PerformanceRange,
    PortfolioHistoryPoint,
    PortfolioPerformanceResponse,
    ReturnAttribution,
    ReturnMetric,
)

Sampling = Literal[
    "daily", "weekly_average", "monthly_average", "adaptive_average"
]
RANGE_DAYS: dict[str, int] = {
    "1w": 6,
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "1y": 365,
    "5y": 1826,
}
SAMPLE_TARGETS: dict[PerformanceRange, int] = {
    "1w": 7,
    "1m": 31,
    "3m": 13,
    "6m": 26,
    "1y": 52,
    "5y": 60,
    "all": 72,
}
SAMPLING_LABELS: dict[PerformanceRange, Sampling] = {
    "1w": "daily",
    "1m": "daily",
    "3m": "weekly_average",
    "6m": "weekly_average",
    "1y": "weekly_average",
    "5y": "monthly_average",
    "all": "adaptive_average",
}
CENT = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _xirr(cash_flows: list[tuple[date, Decimal]]) -> Decimal | None:
    if len(cash_flows) < 2:
        return None
    amounts = [float(amount) for _, amount in cash_flows]
    if not any(amount < 0 for amount in amounts) or not any(
        amount > 0 for amount in amounts
    ):
        return None
    origin = cash_flows[0][0]

    def npv(rate: float) -> float:
        return sum(
            float(amount) / ((1 + rate) ** ((flow_date - origin).days / 365.0))
            for flow_date, amount in cash_flows
        )

    low = -0.9999
    high = 10.0
    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 10
        high_value = npv(high)
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        return None
    if low_value * high_value > 0:
        return None
    for _ in range(180):
        middle = (low + high) / 2
        middle_value = npv(middle)
        if abs(middle_value) < 1e-8:
            return Decimal(str(middle * 100)).quantize(Decimal("0.01"))
        if low_value * middle_value <= 0:
            high = middle
        else:
            low = middle
            low_value = middle_value
    return Decimal(str(((low + high) / 2) * 100)).quantize(Decimal("0.01"))


def _flow_value(row: TransactionRow) -> Decimal | None:
    value = row.transaction.value_eur
    return abs(value) if value is not None else None


def _sample_history_points(
    points: list[PortfolioHistoryPoint], selected_range: PerformanceRange
) -> tuple[list[PortfolioHistoryPoint], Sampling]:
    """Return a bounded chart series without changing performance calculations."""
    target = SAMPLE_TARGETS[selected_range]
    if len(points) <= target:
        return points, "daily"

    sampled: list[PortfolioHistoryPoint] = []
    for bucket_index in range(target):
        start = bucket_index * len(points) // target
        end = (bucket_index + 1) * len(points) // target
        bucket = points[start:end]
        divisor = Decimal(len(bucket))
        sampled.append(
            PortfolioHistoryPoint(
                date=bucket[-1].date,
                total_value_eur=_round_money(
                    sum((point.total_value_eur for point in bucket), Decimal(0))
                    / divisor
                ),
                net_invested_eur=_round_money(
                    sum((point.net_invested_eur for point in bucket), Decimal(0))
                    / divisor
                ),
                invested_value_eur=_round_money(
                    sum((point.invested_value_eur for point in bucket), Decimal(0))
                    / divisor
                ),
            )
        )
    return sampled, SAMPLING_LABELS[selected_range]


def _reconstruct_weekly_history(
    prices: list[HistoricalPriceRow],
    usd_eur_rates: list,
    transactions: list[TransactionRow],
    requested_start: date | None,
    observed_start: date,
    anchor: PortfolioHistoryPoint,
) -> list[PortfolioHistoryPoint]:
    recognized_transactions = [
        row
        for row in transactions
        if row.instrument is not None
        and row.transaction.transaction_type in {TransactionType.BUY, TransactionType.SELL}
        and row.transaction.quantity
    ]
    if not prices or not recognized_transactions:
        return []
    earliest_trade = min(row.transaction.executed_at.date() for row in recognized_transactions)
    reconstruction_start = max(requested_start or earliest_trade, earliest_trade)
    price_dates = sorted(
        {
            row.price.price_date
            for row in prices
            if reconstruction_start <= row.price.price_date < observed_start
        }
    )
    if not price_dates:
        return []

    prices_by_date: dict[date, list[HistoricalPriceRow]] = defaultdict(list)
    for row in prices:
        prices_by_date[row.price.price_date].append(row)
    transactions_by_date: dict[date, list[TransactionRow]] = defaultdict(list)
    for row in recognized_transactions:
        transactions_by_date[row.transaction.executed_at.date()].append(row)

    quantities: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    costs: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    latest_prices: dict[uuid.UUID, HistoricalPriceRow] = {}
    latest_usd_eur: Decimal | None = None
    rates_by_date = {row.rate_date: row.rate for row in usd_eur_rates}
    transaction_dates = sorted(transactions_by_date)
    transaction_index = 0
    rate_dates = sorted(rates_by_date)
    rate_index = 0
    result: list[PortfolioHistoryPoint] = []

    for point_date in price_dates:
        while (
            transaction_index < len(transaction_dates)
            and transaction_dates[transaction_index] <= point_date
        ):
            trade_date = transaction_dates[transaction_index]
            for row in transactions_by_date[trade_date]:
                assert row.instrument is not None
                instrument_id = row.instrument.id
                item = row.transaction
                quantity = abs(item.quantity or Decimal(0))
                value = abs(item.value_eur) if item.value_eur is not None else None
                if value is None and item.value is not None:
                    currency = item.currency.upper()
                    if currency == "EUR":
                        value = abs(item.value)
                    elif currency == "USD":
                        rate_position = bisect_right(rate_dates, trade_date) - 1
                        if rate_position >= 0:
                            value = (
                                abs(item.value)
                                * rates_by_date[rate_dates[rate_position]]
                            )
                if item.transaction_type is TransactionType.BUY:
                    quantities[instrument_id] += quantity
                    if value is not None:
                        costs[instrument_id] += value
                elif quantity and quantities[instrument_id] > 0:
                    sold = min(quantity, quantities[instrument_id])
                    costs[instrument_id] -= costs[instrument_id] * sold / quantities[instrument_id]
                    quantities[instrument_id] -= sold
            transaction_index += 1
        while rate_index < len(rate_dates) and rate_dates[rate_index] <= point_date:
            latest_usd_eur = rates_by_date[rate_dates[rate_index]]
            rate_index += 1
        for row in prices_by_date[point_date]:
            latest_prices[row.instrument.id] = row

        total = Decimal(0)
        invested = Decimal(0)
        for instrument_id, quantity in quantities.items():
            if quantity <= 0 or instrument_id not in latest_prices:
                continue
            price = latest_prices[instrument_id].price
            if price.currency == "EUR":
                eur_price = price.close_price
            elif price.currency == "USD" and latest_usd_eur is not None:
                eur_price = price.close_price * latest_usd_eur
            else:
                continue
            total += quantity * eur_price
            invested += max(Decimal(0), costs[instrument_id])
        if total > 0:
            result.append(
                PortfolioHistoryPoint(
                    date=point_date,
                    total_value_eur=_round_money(total),
                    net_invested_eur=_round_money(invested),
                    invested_value_eur=_round_money(invested),
                )
            )
    if not result or result[-1].total_value_eur <= 0:
        return []
    total_scale = anchor.total_value_eur / result[-1].total_value_eur
    invested_scale = (
        anchor.invested_value_eur / result[-1].invested_value_eur
        if result[-1].invested_value_eur > 0
        else Decimal(1)
    )
    return [
        PortfolioHistoryPoint(
            date=point.date,
            total_value_eur=_round_money(point.total_value_eur * total_scale),
            net_invested_eur=_round_money(point.net_invested_eur * invested_scale),
            invested_value_eur=_round_money(point.invested_value_eur * invested_scale),
        )
        for point in result
    ]


class PerformanceService:
    def __init__(self, repository: PortfolioRepository) -> None:
        self.repository = repository

    async def portfolio(
        self, user_id: uuid.UUID, selected_range: PerformanceRange
    ) -> PortfolioPerformanceResponse:
        snapshots = await self.repository.snapshot_rows(user_id)
        transactions = await self.repository.transaction_rows(user_id)
        if not snapshots:
            unavailable = ReturnMetric(
                percentage=None,
                status="unavailable",
                message="Performance begins after the first successful synchronization.",
            )
            return PortfolioPerformanceResponse(
                range=selected_range,
                start_date=None,
                end_date=None,
                points=[],
                money_weighted_return=unavailable,
                time_weighted_return=unavailable,
                attribution=ReturnAttribution(
                    total_return_eur=None,
                    capital_gain_eur=None,
                    income_eur=Decimal(0),
                    fees_eur=Decimal(0),
                    currency_movement_eur=None,
                    status="unavailable",
                    message="No daily portfolio valuations are available yet.",
                ),
                notices=["History begins when each source is first synchronized."],
            )

        by_connection: dict[uuid.UUID, list[SnapshotRow]] = defaultdict(list)
        for row in snapshots:
            by_connection[row.connection_id].append(row)
        coverage_start = max(
            connection_rows[0].snapshot.snapshot_date
            for connection_rows in by_connection.values()
        )
        end_date = max(row.snapshot.snapshot_date for row in snapshots)
        requested_start = (
            None
            if selected_range == "all"
            else end_date - timedelta(days=RANGE_DAYS[selected_range])
        )
        start_date = (
            coverage_start
            if requested_start is None
            else max(coverage_start, requested_start)
        )

        external_flows: dict[date, Decimal] = defaultdict(Decimal)
        net_invested_by_date: dict[date, Decimal] = defaultdict(Decimal)
        income_by_date: dict[date, Decimal] = defaultdict(Decimal)
        fees_by_date: dict[date, Decimal] = defaultdict(Decimal)
        valued_cash_flows_by_connection: dict[uuid.UUID, list[date]] = defaultdict(list)
        missing_fx = 0
        relevant_types = {
            TransactionType.DEPOSIT,
            TransactionType.WITHDRAWAL,
            TransactionType.DIVIDEND,
            TransactionType.FEE,
        }
        for row in transactions:
            item = row.transaction
            if item.transaction_type not in relevant_types:
                continue
            flow_date = item.executed_at.date()
            value = _flow_value(row)
            if value is None:
                if start_date <= flow_date <= end_date:
                    missing_fx += 1
                continue
            if item.transaction_type is TransactionType.DEPOSIT:
                external_flows[flow_date] += value
                net_invested_by_date[flow_date] += value
                valued_cash_flows_by_connection[row.connection_id].append(flow_date)
            elif item.transaction_type is TransactionType.WITHDRAWAL:
                external_flows[flow_date] -= value
                net_invested_by_date[flow_date] -= value
                valued_cash_flows_by_connection[row.connection_id].append(flow_date)
            elif item.transaction_type is TransactionType.DIVIDEND:
                income_by_date[flow_date] += value
            elif item.transaction_type is TransactionType.FEE:
                fees_by_date[flow_date] += value

        opening_capital_by_date: dict[date, Decimal] = defaultdict(Decimal)
        estimated_opening_sources = 0
        for connection_id, connection_rows in by_connection.items():
            first_snapshot = connection_rows[0].snapshot
            has_usable_prior_cash_flow = any(
                flow_date <= first_snapshot.snapshot_date
                for flow_date in valued_cash_flows_by_connection[connection_id]
            )
            if not has_usable_prior_cash_flow:
                opening_capital_by_date[first_snapshot.snapshot_date] += (
                    first_snapshot.total_value_eur
                )
                estimated_opening_sources += 1

        latest_by_connection: dict[uuid.UUID, SnapshotRow] = {
            connection_id: max(
                (
                    row
                    for row in connection_rows
                    if row.snapshot.snapshot_date <= coverage_start
                ),
                key=lambda row: row.snapshot.snapshot_date,
            )
            for connection_id, connection_rows in by_connection.items()
        }
        snapshot_lookup = {
            (row.connection_id, row.snapshot.snapshot_date): row for row in snapshots
        }
        points: list[PortfolioHistoryPoint] = []
        current_date = coverage_start
        invested = sum(
            (
                value
                for flow_date, value in net_invested_by_date.items()
                if flow_date < coverage_start
            ),
            Decimal(0),
        ) + sum(
            (
                value
                for flow_date, value in opening_capital_by_date.items()
                if flow_date < coverage_start
            ),
            Decimal(0),
        )
        while current_date <= end_date:
            invested += net_invested_by_date[current_date]
            invested += opening_capital_by_date[current_date]
            for connection_id in by_connection:
                new_snapshot = snapshot_lookup.get((connection_id, current_date))
                if new_snapshot is not None:
                    latest_by_connection[connection_id] = new_snapshot
            if current_date >= start_date and latest_by_connection:
                total = sum(
                    (
                        row.snapshot.total_value_eur
                        for row in latest_by_connection.values()
                    ),
                    Decimal(0),
                )
                invested_value = sum(
                    (
                        row.snapshot.total_value_eur
                        - (row.snapshot.reported_pnl_eur or Decimal(0))
                        for row in latest_by_connection.values()
                    ),
                    Decimal(0),
                )
                points.append(
                    PortfolioHistoryPoint(
                        date=current_date,
                        total_value_eur=_round_money(total),
                        net_invested_eur=_round_money(invested),
                        invested_value_eur=_round_money(invested_value),
                    )
                )
            current_date += timedelta(days=1)

        history_method: Literal["observed", "reconstructed"] = "observed"
        price_loader = getattr(self.repository, "historical_price_rows", None)
        rate_loader = getattr(self.repository, "historical_usd_eur_rates", None)
        if price_loader is not None and rate_loader is not None and points:
            historical_prices = await price_loader(user_id, requested_start, end_date)
            historical_rates = await rate_loader(requested_start, end_date)
            reconstructed = _reconstruct_weekly_history(
                historical_prices,
                historical_rates,
                transactions,
                requested_start,
                coverage_start,
                points[0],
            )
            if reconstructed:
                points = reconstructed + points
                history_method = "reconstructed"

        first_point = points[0]
        last_point = points[-1]
        period_flows: dict[date, Decimal] = defaultdict(Decimal)
        for flow_date, value in external_flows.items():
            if first_point.date < flow_date <= last_point.date:
                period_flows[flow_date] += value
        xirr_flows = [(first_point.date, -first_point.total_value_eur)]
        xirr_flows.extend(
            (flow_date, -value)
            for flow_date, value in sorted(period_flows.items())
            if value
        )
        xirr_flows.append((last_point.date, last_point.total_value_eur))
        xirr_value = _xirr(xirr_flows) if first_point.date < last_point.date else None

        twr_factor = Decimal(1)
        twr_periods = 0
        for previous, current in zip(points, points[1:], strict=False):
            if previous.total_value_eur <= 0:
                continue
            flow = period_flows[current.date]
            period_return = (
                current.total_value_eur - previous.total_value_eur - flow
            ) / previous.total_value_eur
            twr_factor *= Decimal(1) + period_return
            twr_periods += 1
        twr_value = (
            ((twr_factor - 1) * 100).quantize(Decimal("0.01"))
            if twr_periods
            else None
        )

        period_income = sum(
            (
                value
                for flow_date, value in income_by_date.items()
                if first_point.date < flow_date <= last_point.date
            ),
            Decimal(0),
        )
        period_fees = sum(
            (
                value
                for flow_date, value in fees_by_date.items()
                if first_point.date < flow_date <= last_point.date
            ),
            Decimal(0),
        )
        net_contributions = sum(period_flows.values(), Decimal(0))
        total_return = (
            last_point.total_value_eur
            - first_point.total_value_eur
            - net_contributions
        )
        currency_movement = self._currency_movement(
            snapshots, first_point.date, last_point.date
        )
        capital_gain = total_return - period_income + period_fees - currency_movement
        status = "partial" if missing_fx else "available"
        metric_message = (
            f"{missing_fx} cash-flow event(s) lack an EUR value."
            if missing_fx
            else None
        )
        notices = [
            "Consolidated history begins when every current source is represented.",
            "Source values are carried forward between synchronization dates.",
            "Currency movement is an estimate based on each source's reported account currency.",
        ]
        if history_method == "reconstructed":
            notices.append(
                "Earlier weekly values are reconstructed from imported trades, cached market "
                "prices, and FX rates, then linked to the first observed portfolio valuation."
            )
        if estimated_opening_sources:
            notices.append(
                f"Opening capital is estimated for {estimated_opening_sources} source(s) "
                "without usable deposit history."
            )
        if missing_fx:
            notices.append(metric_message or "Some activity lacks EUR conversion.")
        chart_points, sampling = _sample_history_points(points, selected_range)
        return PortfolioPerformanceResponse(
            range=selected_range,
            start_date=first_point.date,
            end_date=last_point.date,
            sampling=sampling,
            history_method=history_method,
            points=chart_points,
            money_weighted_return=ReturnMetric(
                percentage=xirr_value,
                status=status if xirr_value is not None else "unavailable",
                message=(
                    metric_message
                    if xirr_value is not None
                    else "XIRR needs valuations on at least two different dates."
                ),
            ),
            time_weighted_return=ReturnMetric(
                percentage=twr_value,
                status=status if twr_value is not None else "unavailable",
                message=(
                    metric_message
                    if twr_value is not None
                    else "TWR needs valuations on at least two different dates."
                ),
            ),
            attribution=ReturnAttribution(
                total_return_eur=_round_money(total_return),
                capital_gain_eur=_round_money(capital_gain),
                income_eur=_round_money(period_income),
                fees_eur=_round_money(period_fees),
                currency_movement_eur=_round_money(currency_movement),
                status="partial" if missing_fx else "estimated",
                message=(
                    metric_message
                    if missing_fx
                    else "Currency movement is estimated; capital gain is the residual."
                ),
            ),
            missing_fx_transaction_count=missing_fx,
            notices=notices,
        )

    @staticmethod
    def _currency_movement(
        snapshots: list[SnapshotRow], start_date: date, end_date: date
    ) -> Decimal:
        movement = Decimal(0)
        by_connection: dict[uuid.UUID, list[SnapshotRow]] = defaultdict(list)
        for row in snapshots:
            if row.snapshot.snapshot_date <= end_date:
                by_connection[row.connection_id].append(row)
        for rows in by_connection.values():
            previous: SnapshotRow | None = None
            for row in rows:
                snapshot = row.snapshot
                if snapshot.currency.upper() == "EUR" or snapshot.total_value == 0:
                    previous = row
                    continue
                if (
                    previous is not None
                    and snapshot.snapshot_date > start_date
                    and previous.snapshot.total_value != 0
                ):
                    old_rate = (
                        previous.snapshot.total_value_eur
                        / previous.snapshot.total_value
                    )
                    new_rate = snapshot.total_value_eur / snapshot.total_value
                    movement += previous.snapshot.total_value * (new_rate - old_rate)
                previous = row
        return movement
