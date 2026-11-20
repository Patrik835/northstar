"""Run with REVIEW_TEST_DATABASE_URL pointing to a disposable PostgreSQL database."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_connection_sync import EurRates, FakeConnector

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base
from app.core.encryption import CredentialCipher
from app.core.security import digest_session_token, hash_password
from app.models.broker import BrokerConnection
from app.models.enums import Broker
from app.models.sync import SyncRun
from app.models.user import PasswordResetToken, User
from app.services.account_data import AccountDataService, LastAdministratorError
from app.services.connection_sync import ConnectionSyncService
from app.services.password_recovery import InvalidPasswordResetTokenError, PasswordRecoveryService


@pytest_asyncio.fixture
async def postgres():
    url = os.getenv("REVIEW_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires disposable PostgreSQL database")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_reset_claim_is_single_use_under_overlap(postgres):
    async with postgres() as db:
        user = User(username="reset", password_hash=hash_password("old-password"))
        db.add(user)
        await db.flush()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_digest=digest_session_token("token"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db.commit()
    arrived = 0
    ready = asyncio.Event()

    class OverlappingSession(AsyncSession):
        async def scalar(self, statement, *args, **kwargs):
            nonlocal arrived
            result = await super().scalar(statement, *args, **kwargs)
            arrived += 1
            if arrived == 2:
                ready.set()
            await ready.wait()
            return result

    async def reset(password):
        async with OverlappingSession(bind=postgres.kw["bind"], expire_on_commit=False) as db:
            try:
                await PasswordRecoveryService(db, get_settings(), None).reset("token", password)
                return True
            except InvalidPasswordResetTokenError:
                return False

    results = await asyncio.wait_for(
        asyncio.gather(reset("password-one"), reset("password-two")), 15
    )
    assert sorted(results) == [False, True]


async def test_admin_deletion_preserves_one_admin(postgres):
    async with postgres() as db:
        users = [
            User(username=name, password_hash=hash_password("password"), is_admin=True)
            for name in ["first", "second"]
        ]
        db.add_all(users)
        await db.commit()
        ids = [user.id for user in users]
    ready = asyncio.Event()
    arrived = 0

    async def remove(user_id):
        nonlocal arrived
        async with postgres() as db:
            user = await db.get(User, user_id)
            arrived += 1
            if arrived == 2:
                ready.set()
            await ready.wait()
            try:
                await AccountDataService(db).delete(user, "password")
                return True
            except LastAdministratorError:
                return False

    results = await asyncio.wait_for(asyncio.gather(*(remove(user_id) for user_id in ids)), 15)
    assert sorted(results) == [False, True]
    async with postgres() as db:
        assert await db.scalar(select(func.count()).select_from(User).where(User.is_admin)) == 1


async def test_connection_sync_excludes_overlapping_workers(postgres):
    cipher = CredentialCipher()
    async with postgres() as db:
        user = User(username="sync", password_hash=hash_password("password"))
        db.add(user)
        await db.flush()
        connection = BrokerConnection(
            user_id=user.id,
            broker=Broker.TRADING212,
            encrypted_credentials=cipher.encrypt({}),
            credential_hint="test",
        )
        db.add(connection)
        await db.commit()
        connection_id = connection.id
    active = 0
    maximum = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowConnector(FakeConnector):
        async def validate_credentials(self):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            entered.set()
            await release.wait()
            active -= 1

    async def sync():
        async with postgres() as db:
            connection = await db.get(BrokerConnection, connection_id)
            return await ConnectionSyncService(db, cipher, EurRates()).sync(
                connection, SlowConnector()
            )

    first = asyncio.create_task(sync())
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(sync())
    try:
        overlapping = await asyncio.wait_for(second, 5)
        assert overlapping.id == connection_id
    finally:
        release.set()
    await asyncio.wait_for(first, 15)
    assert maximum == 1
    async with postgres() as db:
        assert await db.scalar(select(func.count()).select_from(SyncRun)) == 1


async def test_manual_quote_fetch_does_not_block_or_overwrite_edits(postgres):
    from decimal import Decimal

    from app.models.enums import AssetType
    from app.models.portfolio import Position
    from app.schemas.portfolio import ManualPositionWrite
    from app.services.manual_positions import ManualPositionService

    cipher = CredentialCipher()
    async with postgres() as db:
        user = User(username="manual", password_hash=hash_password("password"))
        db.add(user)
        await db.commit()
        user_id = user.id
        position = await ManualPositionService(db, cipher, EurRates()).create(
            user_id,
            ManualPositionWrite(
                ticker="BTC",
                asset_type=AssetType.CRYPTO,
                quantity=Decimal(1),
                average_price=Decimal(100),
                current_price=Decimal(120),
                currency="EUR",
            ),
        )
        position_id = position.id
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowPrices:
        async def price(self, ticker, asset_type):
            entered.set()
            await release.wait()
            return Decimal(150), "EUR", datetime.now(timezone.utc)

    async def refresh():
        async with postgres() as db:
            await ManualPositionService(db, cipher, EurRates(), SlowPrices()).refresh(user_id)

    task = asyncio.create_task(refresh())
    await asyncio.wait_for(entered.wait(), 5)
    try:
        async with postgres() as db:
            await asyncio.wait_for(
                ManualPositionService(db, cipher, EurRates()).update(
                    user_id,
                    position_id,
                    ManualPositionWrite(
                        ticker="BTC",
                        asset_type=AssetType.CRYPTO,
                        quantity=Decimal(2),
                        average_price=Decimal(100),
                        current_price=Decimal(120),
                        currency="EUR",
                    ),
                ),
                5,
            )
    finally:
        release.set()
    await asyncio.wait_for(task, 5)
    async with postgres() as db:
        position = await db.get(Position, position_id)
        assert position.quantity == Decimal(2)
        assert position.current_value_eur == Decimal(240)
