import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.encryption import CredentialCipher
from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker
from app.models.portfolio import PortfolioSnapshot, Position
from app.models.user import User
from app.repositories.connections import ConnectionRepository
from app.schemas.portfolio import ManualPositionWrite
from app.services.manual_positions import ManualPositionService


class FixedUsdRates:
    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of=None
    ) -> Decimal:
        return value if currency == "EUR" else value * Decimal("0.8")


@pytest.mark.asyncio
async def test_manual_position_create_update_delete_and_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cipher = CredentialCipher()
    try:
        async with factory() as db:
            user = User(username="manual-owner", password_hash="unused")
            db.add(user)
            await db.commit()
            service = ManualPositionService(db, cipher, FixedUsdRates())

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
            await db.refresh(snapshot)
            assert snapshot.total_value_eur == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_position_is_tenant_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            first = User(username="manual-first", password_hash="unused")
            second = User(username="manual-second", password_hash="unused")
            db.add_all([first, second])
            await db.commit()
            service = ManualPositionService(db, CredentialCipher(), FixedUsdRates())
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
            assert await service.update(
                second.id,
                created.id,
                ManualPositionWrite(
                    ticker="ETH",
                    asset_type=AssetType.CRYPTO,
                    quantity=Decimal("2"),
                    current_price=Decimal("3000"),
                    currency="EUR",
                ),
            ) is None
            assert await service.delete(second.id, created.id) is False
    finally:
        await engine.dispose()
