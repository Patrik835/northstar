from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.core.encryption import CredentialCipher
from app.integrations.market_data.current_prices import CurrentPriceError
from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker
from app.models.instrument import InstrumentAlias
from app.models.portfolio import PortfolioSnapshot, Position
from app.models.user import User
from app.repositories.connections import ConnectionRepository
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import ManualPositionWrite
from app.services.manual_positions import ManualPositionService
from app.services.portfolio import PortfolioService


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: Any) -> None:
        self.session.add(item)

    def add_all(self, items: list[Any]) -> None:
        self.session.add_all(items)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def refresh(self, item: Any) -> None:
        self.session.refresh(item)

    async def execute(self, statement: Any):
        return self.session.execute(statement)

    async def scalar(self, statement: Any):
        return self.session.scalar(statement)

    async def scalars(self, statement: Any):
        return self.session.scalars(statement)

    async def get(self, model: type, item_id: Any):
        return self.session.get(model, item_id)

    async def delete(self, item: Any) -> None:
        self.session.delete(item)


class UnavailablePrices:
    async def price(self, ticker, asset_type):
        raise CurrentPriceError("Offline")


class FixedUsdRates:
    async def convert_to_eur(self, value: Decimal, currency: str, as_of=None) -> Decimal:
        return value if currency == "EUR" else value * Decimal("0.8")


@pytest.mark.asyncio
async def test_purchase_only_holding_preserves_note_without_inventing_profit() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            user = User(username="purchase-only", password_hash="unused")
            db.add(user)
            await db.commit()
            service = ManualPositionService(
                db, CredentialCipher(), FixedUsdRates(), UnavailablePrices()
            )
            payload = ManualPositionWrite(
                ticker="BTC",
                name="Bitcoin",
                asset_type=AssetType.CRYPTO,
                quantity=Decimal("0.5"),
                average_price=Decimal("50000"),
                note="  Stored in my hardware wallet  ",
            )
            created = await service.create(user.id, payload)
            assert created.current_value_eur == Decimal("25000")
            assert created.current_price is None
            assert created.open_pnl is None
            assert (await service.list(user.id))[0].note == "Stored in my hardware wallet"
            portfolio = await PortfolioService(PortfolioRepository(db)).holdings(user.id)
            holding = portfolio.holdings[0]
            assert holding.name == "Bitcoin"
            assert holding.sources[0].note == "Stored in my hardware wallet"
            assert holding.sources[0].valuation_source == "manual_cost"
            assert holding.performance.open_pnl_eur is None
            updated = await service.update(
                user.id,
                created.id,
                payload.model_copy(update={"quantity": Decimal("1"), "note": None}),
            )
            assert updated is not None
            assert updated.current_value_eur == Decimal("50000")
            assert updated.note is None
            snapshot = await db.scalar(select(PortfolioSnapshot))
            assert snapshot.total_value_eur == Decimal("50000")
    finally:
        engine.dispose()


def test_purchase_only_holding_requires_positive_purchase_price() -> None:
    from pydantic import ValidationError

    for price in (None, Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            ManualPositionWrite(
                ticker="BTC",
                asset_type=AssetType.CRYPTO,
                quantity=Decimal("1"),
                average_price=price,
            )


@pytest.mark.asyncio
async def test_manual_position_create_update_delete_and_snapshot() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cipher = CredentialCipher()
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            user = User(username="manual-owner", password_hash="unused")
            db.add(user)
            await db.commit()
            service = ManualPositionService(  # type: ignore[arg-type]
                db, cipher, FixedUsdRates(), UnavailablePrices()
            )

            created = await service.create(
                user.id,
                ManualPositionWrite(
                    ticker="aapl",
                    name="Apple Inc.",
                    asset_type=AssetType.STOCK,
                    quantity=Decimal("2"),
                    average_price=Decimal("100"),
                    current_price=Decimal("125"),
                    currency="USD",
                    isin="US0378331005",
                ),
            )

            assert created.ticker == "AAPL"
            assert created.current_value == Decimal("250")
            assert created.current_value_eur == Decimal("200.0")
            assert created.open_pnl_eur == Decimal("40.0")
            assert len(await service.list(user.id)) == 1
            connection = await db.scalar(
                select(BrokerConnection).where(BrokerConnection.broker == Broker.MANUAL)
            )
            assert connection is not None
            assert await ConnectionRepository(db).for_user(user.id) == []
            position = await db.get(Position, created.id)
            assert position is not None
            assert position.valuation_source == "manual"
            assert position.is_estimated is True

            updated = await service.update(
                user.id,
                created.id,
                ManualPositionWrite(
                    ticker="BTC",
                    name="Bitcoin",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("0.5"),
                    average_price=Decimal("50000"),
                    current_price=Decimal("60000"),
                    currency="EUR",
                ),
            )

            assert updated is not None
            assert updated.ticker == "BTC"
            assert updated.current_value_eur == Decimal("30000")
            snapshot = await db.scalar(select(PortfolioSnapshot))
            assert snapshot is not None
            assert snapshot.total_value_eur == Decimal("30000")

            assert await service.delete(user.id, created.id) is True
            assert await service.list(user.id) == []
            assert await db.scalar(select(func.count(Position.id))) == 0
            assert await db.scalar(select(func.count(InstrumentAlias.id))) == 0
            await db.refresh(snapshot)
            assert snapshot.total_value_eur == 0
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_manual_position_is_tenant_scoped() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            first = User(username="manual-first", password_hash="unused")
            second = User(username="manual-second", password_hash="unused")
            db.add_all([first, second])
            await db.commit()
            service = ManualPositionService(  # type: ignore[arg-type]
                db, CredentialCipher(), FixedUsdRates(), UnavailablePrices()
            )
            created = await service.create(
                first.id,
                ManualPositionWrite(
                    ticker="ETH",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("1"),
                    current_price=Decimal("3000"),
                    currency="EUR",
                ),
            )

            assert await service.list(second.id) == []
            assert (
                await service.update(
                    second.id,
                    created.id,
                    ManualPositionWrite(
                        ticker="ETH",
                        asset_type=AssetType.CRYPTO,
                        quantity=Decimal("2"),
                        current_price=Decimal("3000"),
                        currency="EUR",
                    ),
                )
                is None
            )
            assert await service.delete(second.id, created.id) is False
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_market_price_refresh_updates_profit_loss_and_snapshot() -> None:
    from datetime import datetime, timezone

    class Prices:
        value = Decimal("150")
        unavailable = False

        async def price(self, ticker, asset_type):
            if self.unavailable:
                raise CurrentPriceError("Offline")
            return self.value, "USD", datetime.now(timezone.utc)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            user = User(username="market-owner", password_hash="unused")
            other = User(username="market-other", password_hash="unused")
            db.add_all([user, other])
            await db.commit()
            prices = Prices()
            service = ManualPositionService(db, CredentialCipher(), FixedUsdRates(), prices)
            created = await service.create(
                user.id,
                ManualPositionWrite(
                    ticker="AAPL",
                    asset_type=AssetType.STOCK,
                    quantity=Decimal("2"),
                    average_price=Decimal("100"),
                    currency="USD",
                ),
            )
            assert created.current_price == Decimal("150")
            assert created.open_pnl == Decimal("100")
            assert created.open_pnl_eur == Decimal("80")
            prices.value = Decimal("75")
            await service.refresh(other.id)
            assert (await db.get(Position, created.id)).current_value == Decimal("300")
            refreshed = (await service.list(user.id))[0]
            assert refreshed.current_value_eur == Decimal("120")
            assert refreshed.open_pnl == Decimal("-50")
            assert refreshed.open_pnl_eur == Decimal("-40")
            portfolio = await PortfolioService(PortfolioRepository(db)).holdings(user.id)
            assert portfolio.holdings[0].performance.open_pnl_eur == Decimal("-40")
            assert portfolio.holdings[0].performance.open_pnl_percentage == Decimal("-25")
            assert (await db.scalar(select(PortfolioSnapshot))).total_value_eur == Decimal("120")
            connection = await db.scalar(select(BrokerConnection))
            successful_at = connection.last_successful_sync_at
            prices.unavailable = True
            stale = (await service.list(user.id))[0]
            assert stale.valued_at == refreshed.valued_at
            assert stale.open_pnl_eur == Decimal("-40")
            assert connection.last_successful_sync_at == successful_at
            assert connection.last_error is not None
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_manual_purchases_merge_quantity_weighted_cost_notes_and_pnl() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            user = User(username="merged-owner", password_hash="unused")
            db.add(user)
            await db.commit()
            service = ManualPositionService(
                db, CredentialCipher(), FixedUsdRates(), UnavailablePrices()
            )
            first = await service.create(
                user.id,
                ManualPositionWrite(
                    ticker="BTC",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("1"),
                    average_price=Decimal("100"),
                    current_price=Decimal("200"),
                    currency="EUR",
                    note="Wallet one",
                ),
            )
            merged = await service.create(
                user.id,
                ManualPositionWrite(
                    ticker="BTC",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("3"),
                    average_price=Decimal("200"),
                    current_price=Decimal("250"),
                    currency="USD",
                    note="Wallet two",
                ),
            )
            assert merged.id == first.id
            assert merged.quantity == Decimal("4")
            assert merged.average_price == Decimal("145")
            assert merged.current_value_eur == Decimal("800")
            assert merged.open_pnl_eur == Decimal("220")
            assert merged.note == "Wallet one\n\nWallet two"
            assert len(await service.list(user.id)) == 1
            assert await db.scalar(select(func.count(InstrumentAlias.id))) == 1
            portfolio = await PortfolioService(PortfolioRepository(db)).holdings(user.id)
            assert portfolio.position_count == 1
            assert portfolio.holdings[0].source_count == 1
            assert portfolio.holdings[0].performance.open_pnl_eur == Decimal("220")
            edited = await service.update(
                user.id,
                merged.id,
                ManualPositionWrite(
                    ticker="BTC",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("2"),
                    average_price=Decimal("145"),
                    current_price=Decimal("200"),
                    currency="EUR",
                ),
            )
            assert edited.quantity == Decimal("2")
            assert edited.open_pnl_eur == Decimal("110")
            assert await service.delete(user.id, merged.id)
            assert await service.list(user.id) == []
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_refresh_consolidates_existing_manual_entries_without_losing_cost() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            user = User(username="legacy-owner", password_hash="unused")
            db.add(user)
            await db.commit()
            service = ManualPositionService(
                db, CredentialCipher(), FixedUsdRates(), UnavailablePrices()
            )
            connection = await service._connection(user.id)
            import uuid

            for quantity, price in (("1", "100"), ("2", "250")):
                identifier = uuid.uuid4()
                position, _ = await service._build_position(
                    connection,
                    identifier,
                    f"MANUAL:{identifier}",
                    ManualPositionWrite(
                        ticker="ETH",
                        asset_type=AssetType.CRYPTO,
                        quantity=Decimal(quantity),
                        average_price=Decimal(price),
                        currency="EUR",
                    ),
                )
                db.add(position)
            await db.commit()
            merged = (await service.list(user.id))[0]
            assert merged.quantity == Decimal("3")
            assert merged.average_price == Decimal("200")
            assert merged.current_value_eur == Decimal("600")
            assert merged.open_pnl_eur is None
            assert len(await service.list(user.id)) == 1
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_page_load_refresh_reuses_recent_quotes_and_fetches_in_parallel() -> None:
    import asyncio
    from datetime import datetime, timedelta, timezone

    class Prices:
        calls: list[str] = []
        in_flight = 0
        max_in_flight = 0

        async def price(self, ticker, asset_type):
            self.calls.append(ticker)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            return Decimal("150"), "USD", datetime.now(timezone.utc)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            db = AsyncSessionAdapter(session)
            user = User(username="quote-owner", password_hash="unused")
            db.add(user)
            await db.commit()
            prices = Prices()
            service = ManualPositionService(db, CredentialCipher(), FixedUsdRates(), prices)
            for ticker in ("AAPL", "MSFT", "NVDA"):
                await service.create(
                    user.id,
                    ManualPositionWrite(
                        ticker=ticker,
                        asset_type=AssetType.STOCK,
                        quantity=Decimal("1"),
                        average_price=Decimal("100"),
                        currency="USD",
                    ),
                )

            prices.calls.clear()
            await service.refresh(user.id, max_age=timedelta(minutes=5))
            # Adding holdings just quoted them, so an immediate page load reuses that.
            assert prices.calls == []

            connection = await db.scalar(select(BrokerConnection))
            connection.last_sync_attempt_at = datetime.now(timezone.utc) - timedelta(hours=1)
            await db.commit()
            prices.max_in_flight = 0
            await service.refresh(user.id, max_age=timedelta(minutes=5))
            # Once quotes are old, the next page load quotes every listing, all at once.
            assert sorted(prices.calls) == ["AAPL", "MSFT", "NVDA"]
            assert prices.max_in_flight == 3

            prices.calls.clear()
            await service.refresh(user.id, max_age=timedelta(minutes=5))
            # A reload within the freshness window doesn't call the price provider at all.
            assert prices.calls == []

            await service.refresh(user.id)
            # Explicit refreshes (no window) always re-quote.
            assert sorted(prices.calls) == ["AAPL", "MSFT", "NVDA"]
    finally:
        engine.dispose()
