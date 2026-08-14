import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.integrations.market_data import FxRateError
from app.models.enums import AssetType, Broker, TransactionType
from app.models.instrument import Instrument
from app.models.portfolio import Transaction
from app.repositories.portfolio import TransactionRow
from app.services.activity import ActivityService


class ActivityRepository:
    def __init__(self, rows: list[TransactionRow]) -> None:
        self.rows = rows

    async def transaction_rows(self, _user_id: uuid.UUID) -> list[TransactionRow]:
        return self.rows


def row(
    symbol: str,
    transaction_type: TransactionType,
    broker: Broker,
    day: int,
) -> TransactionRow:
    connection_id = uuid.uuid4()
    instrument = Instrument(
        id=uuid.uuid4(),
        identity_key=f"SECURITY:{symbol}",
        canonical_symbol=symbol,
        name=f"{symbol} Incorporated",
        asset_type=AssetType.STOCK,
    )
    return TransactionRow(
        transaction=Transaction(
            id=uuid.uuid4(),
            broker_connection_id=connection_id,
            external_id=f"{symbol}-{day}",
            ticker=symbol,
            transaction_type=transaction_type,
            quantity=Decimal("1"),
            price=Decimal("10"),
            value=Decimal("10"),
            value_eur=Decimal("10"),
            currency="EUR",
            executed_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        ),
        broker=broker,
        connection_id=connection_id,
        instrument=instrument,
    )


@pytest.mark.asyncio
async def test_activity_filters_and_returns_newest_first() -> None:
    rows = [
        row("AAA", TransactionType.BUY, Broker.TRADING212, 1),
        row("BBB", TransactionType.DIVIDEND, Broker.XTB, 2),
        row("AAA", TransactionType.SELL, Broker.TRADING212, 3),
    ]
    service = ActivityService(ActivityRepository(rows))  # type: ignore[arg-type]

    result = await service.list(
        uuid.uuid4(), broker=Broker.TRADING212, search="aaa", limit=10
    )

    assert result.total == 2
    assert [item.transaction_type for item in result.items] == [
        TransactionType.SELL,
        TransactionType.BUY,
    ]
    assert all(item.holding_key == "company:aaa" for item in result.items)


@pytest.mark.asyncio
async def test_display_activity_has_only_trades_and_dividends() -> None:
    rows = [
        row("AAA", TransactionType.BUY, Broker.TRADING212, 1),
        row("AAA", TransactionType.SELL, Broker.TRADING212, 2),
        row("AAA", TransactionType.DIVIDEND, Broker.TRADING212, 3),
        row("AAA", TransactionType.DEPOSIT, Broker.TRADING212, 4),
        row("AAA", TransactionType.WITHDRAWAL, Broker.TRADING212, 5),
        row("AAA", TransactionType.FEE, Broker.TRADING212, 6),
    ]
    service = ActivityService(ActivityRepository(rows))  # type: ignore[arg-type]

    visible = await service.list(uuid.uuid4(), display_only=True)
    trades = await service.list(
        uuid.uuid4(), display_only=True, activity_group="trade"
    )

    assert {item.transaction_type for item in visible.items} == {
        TransactionType.BUY,
        TransactionType.SELL,
        TransactionType.DIVIDEND,
    }
    assert {item.transaction_type for item in trades.items} == {
        TransactionType.BUY,
        TransactionType.SELL,
    }
    assert trades.summary.bought.value_eur == Decimal("10")
    assert trades.summary.sold.value_eur == Decimal("10")
    assert trades.summary.dividends.value_eur == Decimal("10")
    assert trades.summary.deposited.value_eur == Decimal("0")


@pytest.mark.asyncio
async def test_activity_summary_reports_missing_eur_coverage() -> None:
    missing = row("AAA", TransactionType.DIVIDEND, Broker.XTB, 2)
    missing.transaction.value_eur = None
    missing.transaction.currency = "USD"

    class HistoricalRates:
        async def convert_to_eur(
            self, value: Decimal, currency: str, as_of: object = None
        ) -> Decimal:
            assert currency == "USD"
            assert as_of is not None
            return value * Decimal("0.8")

    service = ActivityService(  # type: ignore[arg-type]
        ActivityRepository([missing]), fx_rates=HistoricalRates()
    )

    result = await service.list(uuid.uuid4(), display_only=True)

    assert result.summary.dividends.value_eur == Decimal("8.0")
    assert result.summary.dividends.event_count == 1
    assert result.summary.dividends.missing_eur_count == 0
    assert result.summary.dividends.estimated_eur_count == 0
    assert result.summary.dividends.native_values == []
    assert result.items[0].value_eur == Decimal("8.0")
    assert result.items[0].is_estimated_fx is False


@pytest.mark.asyncio
async def test_activity_uses_latest_rate_when_historical_fx_is_unavailable() -> None:
    missing = row("AAA", TransactionType.SELL, Broker.ETORO, 2)
    missing.transaction.value_eur = None
    missing.transaction.currency = "USD"

    class LatestRates:
        async def convert_to_eur(
            self, value: Decimal, _currency: str, as_of: object = None
        ) -> Decimal:
            if as_of is not None:
                raise FxRateError("Historical rate unavailable")
            return value * Decimal("0.75")

    service = ActivityService(  # type: ignore[arg-type]
        ActivityRepository([missing]), fx_rates=LatestRates()
    )

    result = await service.list(uuid.uuid4(), display_only=True)

    assert result.summary.sold.value_eur == Decimal("7.50")
    assert result.summary.sold.missing_eur_count == 0
    assert result.summary.sold.estimated_eur_count == 1
    assert result.items[0].is_estimated_fx is True
