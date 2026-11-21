"""The scheduled job keeps hand-added holdings priced so page loads never wait on quotes."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.broker import BrokerConnection
from app.models.enums import Broker
from app.models.user import User
from app.scheduling import jobs


@pytest.mark.asyncio
async def test_refresh_manual_prices_reprices_every_manual_user_and_isolates_failures(
    monkeypatch,
):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            failing = User(username="failing", password_hash="unused")
            manual = User(username="manual", password_hash="unused")
            broker_only = User(username="broker-only", password_hash="unused")
            db.add_all([failing, manual, broker_only])
            await db.flush()
            for user, broker in (
                (failing, Broker.MANUAL),
                (manual, Broker.MANUAL),
                (manual, Broker.TRADING212),
                (broker_only, Broker.TRADING212),
            ):
                db.add(
                    BrokerConnection(
                        user_id=user.id,
                        broker=broker,
                        encrypted_credentials=b"",
                        credential_hint="",
                    )
                )
            await db.commit()

        refreshed = []

        class FakeService:
            def __init__(self, db, cipher):
                pass

            async def refresh(self, user_id, *, max_age=None):
                if user_id == failing.id:
                    raise RuntimeError("provider exploded")
                refreshed.append(user_id)

        monkeypatch.setattr(jobs, "SessionFactory", factory)
        monkeypatch.setattr(jobs, "ManualPositionService", FakeService)
        await jobs.refresh_manual_prices()

        # Each user with manual holdings is re-priced once, even when another user's update
        # fails; users without manual holdings are skipped.
        assert refreshed == [manual.id]
    finally:
        await engine.dispose()
