"""End-to-end first-run flow: a fresh install needs no bootstrap command or mailbox."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


async def test_first_registration_creates_signed_in_ready_admin(client: httpx.AsyncClient):
    status = (await client.get("/api/v1/auth/setup")).json()
    assert status["needs_setup"] is True
    assert status["signup_enabled"] is True

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "owner",
            "email": "owner@example.com",
            "password": "a-secure-password",
            "password_confirmation": "a-secure-password",
        },
    )
    assert registered.status_code == 202
    assert registered.json()["active"] is True

    login = await client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "a-secure-password"}
    )
    assert login.status_code == 200
    assert login.json()["is_admin"] is True
    assert (await client.get("/api/v1/auth/setup")).json()["needs_setup"] is False
