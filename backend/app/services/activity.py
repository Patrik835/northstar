import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Literal, Protocol

from app.integrations.market_data import (
    BinanceCryptoPriceProvider,
    CryptoPriceError,
    FxRateError,
    FxRateProvider,
)
from app.models.enums import Broker, TransactionType
from app.repositories.portfolio import PortfolioRepository
from app.schemas.activity import (
    ActivityCurrencyTotal,
    ActivityItem,
    ActivityResponse,
    ActivitySummary,
    ActivityTotal,
)
from app.services.portfolio import transaction_holding_key


class CryptoPriceProvider(Protocol):
    async def rates_to_eur(self, assets: set[str]) -> dict[str, Decimal]: ...


class ActivityService:
    def __init__(
        self,
        repository: PortfolioRepository,
        fx_rates: FxRateProvider | None = None,
        crypto_prices: CryptoPriceProvider | None = None,
    ) -> None:
        self.repository = repository
        self.fx_rates = fx_rates
        self.crypto_prices = crypto_prices or BinanceCryptoPriceProvider()

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        broker: Broker | None = None,
        transaction_type: TransactionType | None = None,
        activity_group: Literal["trade", "dividend", "deposit"] | None = None,
        display_only: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
        holding_key: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> ActivityResponse:
        rows = await self.repository.transaction_rows(user_id)
        query = (search or "").strip().casefold()
        start = (
            datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            if date_from
            else None
        )
        end = (
            datetime.combine(date_to, time.max, tzinfo=timezone.utc) if date_to else None
        )
        items: list[ActivityItem] = []
        conversion_cache: dict[tuple[str, date], tuple[Decimal | None, bool]] = {}
        summary_values = {
            kind: {"value": Decimal(0), "events": 0, "missing": 0, "estimated": 0}
            for kind in (
                TransactionType.BUY,
                TransactionType.SELL,
                TransactionType.DIVIDEND,
                TransactionType.DEPOSIT,
            )
        }
        native_summary_values: dict[
            TransactionType, dict[str, dict[str, Decimal | int]]
        ] = {
            kind: {}
            for kind in (
                TransactionType.BUY,
                TransactionType.SELL,
                TransactionType.DIVIDEND,
                TransactionType.DEPOSIT,
            )
        }
        for row in reversed(rows):
            transaction = row.transaction
            row_holding_key = transaction_holding_key(row)
            visible_types = {
                TransactionType.BUY,
                TransactionType.SELL,
                TransactionType.DIVIDEND,
            }
            if display_only and transaction.transaction_type not in visible_types:
                continue
            if broker is not None and row.broker is not broker:
                continue
            executed_at = transaction.executed_at
            comparable = (
                executed_at.replace(tzinfo=timezone.utc)
                if executed_at.tzinfo is None
                else executed_at
            )
            if start is not None and comparable < start:
                continue
            if end is not None and comparable > end:
                continue
            if holding_key is not None and row_holding_key != holding_key:
                continue
            name = row.instrument.name if row.instrument else None
            symbol = (
                row.instrument.canonical_symbol
                if row.instrument
                else transaction.ticker
            )
            if query and query not in " ".join(
                [symbol, name or "", transaction.ticker, row.broker.value]
            ).casefold():
                continue
            value_eur = transaction.value_eur
            estimated_fx = False
            if value_eur is None:
                rate, estimated_fx = await self._rate_to_eur(
                    transaction.currency,
                    comparable.date(),
                    conversion_cache,
                )
                if rate is not None:
                    value_eur = transaction.value * rate
            if transaction.transaction_type in summary_values:
                total = summary_values[transaction.transaction_type]
                total["events"] += 1
                if value_eur is None:
                    total["missing"] += 1
                    currency = transaction.currency.upper()
                    native = native_summary_values[transaction.transaction_type].setdefault(
                        currency, {"value": Decimal(0), "events": 0}
                    )
                    native["value"] += abs(transaction.value)
                    native["events"] += 1
                else:
                    total["value"] += abs(value_eur)
                    if estimated_fx:
                        total["estimated"] += 1
            if activity_group == "trade" and transaction.transaction_type not in {
                TransactionType.BUY,
                TransactionType.SELL,
            }:
                continue
            if (
                activity_group in {"dividend", "deposit"}
                and transaction.transaction_type.value != activity_group
            ):
                continue
            if (
                transaction_type is not None
                and transaction.transaction_type is not transaction_type
            ):
                continue
            items.append(
                ActivityItem(
                    id=transaction.id,
                    broker=row.broker,
                    connection_id=row.connection_id,
                    holding_key=row_holding_key,
                    symbol=symbol,
                    name=name,
                    transaction_type=transaction.transaction_type,
                    quantity=transaction.quantity,
                    price=transaction.price,
                    value=transaction.value,
                    value_eur=value_eur,
                    is_estimated_fx=estimated_fx,
                    currency=transaction.currency,
                    executed_at=transaction.executed_at,
                )
            )
        total = len(items)

        def activity_total(kind: TransactionType) -> ActivityTotal:
            values = summary_values[kind]
            return ActivityTotal(
                value_eur=values["value"],
                event_count=int(values["events"]),
                missing_eur_count=int(values["missing"]),
                estimated_eur_count=int(values["estimated"]),
                native_values=[
                    ActivityCurrencyTotal(
                        currency=currency,
                        value=currency_values["value"],
                        event_count=int(currency_values["events"]),
                    )
                    for currency, currency_values in sorted(
                        native_summary_values[kind].items()
                    )
                ],
            )

        return ActivityResponse(
            items=items[offset : offset + limit],
            total=total,
            offset=offset,
            limit=limit,
            brokers=sorted({item.broker for item in items}, key=lambda item: item.value),
            transaction_types=sorted(
                {item.transaction_type for item in items}, key=lambda item: item.value
            ),
            summary=ActivitySummary(
                bought=activity_total(TransactionType.BUY),
                sold=activity_total(TransactionType.SELL),
                dividends=activity_total(TransactionType.DIVIDEND),
                deposited=activity_total(TransactionType.DEPOSIT),
            ),
        )

    async def _rate_to_eur(
        self,
        currency: str,
        as_of: date,
        cache: dict[tuple[str, date], tuple[Decimal | None, bool]],
    ) -> tuple[Decimal | None, bool]:
        normalized = currency.strip().upper()
        key = (normalized, as_of)
        if key in cache:
            return cache[key]
        if normalized == "EUR":
            cache[key] = (Decimal(1), False)
            return cache[key]
        if self.fx_rates is not None:
            try:
                rate = await self.fx_rates.convert_to_eur(
                    Decimal(1), normalized, as_of
                )
                cache[key] = (rate, False)
                return cache[key]
            except FxRateError:
                try:
                    rate = await self.fx_rates.convert_to_eur(Decimal(1), normalized)
                    cache[key] = (rate, True)
                    return cache[key]
                except FxRateError:
                    pass
        try:
            rate = (await self.crypto_prices.rates_to_eur({normalized})).get(normalized)
        except CryptoPriceError:
            rate = None
        cache[key] = (rate, rate is not None)
        return cache[key]
