from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base
from app.core.security import hash_password, verify_password
from app.integrations.email.base import EmailSender
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus
from app.models.user import AuthRateLimitEvent, PasswordResetToken, User, UserSession
from app.services.account_data import AccountDataService, LastAdministratorError
from app.services.auth_rate_limit import AuthRateLimiter, AuthRateLimitExceeded
from app.services.password_recovery import (
    InvalidPasswordResetTokenError,
    PasswordRecoveryService,
)


class CapturingRecoverySender(EmailSender):
    def __init__(self) -> None:
        self.reset_url: str | None = None

    async def send_verification_email(
        self, *, recipient: str, username: str, verification_url: str
    ) -> None:
        raise AssertionError("Verification email was not expected")

    async def send_password_reset_email(
        self,
        *,
        recipient: str,
        username: str,
        reset_url: str,
        expires_minutes: int,
    ) -> None:
        self.reset_url = reset_url


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item) -> None:
        self.session.add(item)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def get(self, model, identifier):
        return self.session.get(model, identifier)

    async def refresh(self, item) -> None:
        self.session.refresh(item)

    async def delete(self, item) -> None:
        self.session.delete(item)


def _database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_password_reset_token_is_hashed_single_use_and_revokes_sessions() -> None:
    engine, factory = _database()
    try:
        with factory() as session:
            db = AsyncSessionAdapter(session)
            user = User(
                username="reset-user",
                email="reset@example.com",
                password_hash=hash_password("old-password-123"),
            )
            db.add(user)
            await db.flush()
            db.add(
                UserSession(
                    user_id=user.id,
                    token_digest="a" * 64,
                    expires_at=user.created_at,
                )
            )
            await db.commit()

            sender = CapturingRecoverySender()
            service = PasswordRecoveryService(db, get_settings(), sender)  # type: ignore[arg-type]
            await service.request(" RESET@example.com ")

            assert sender.reset_url is not None
            raw_token = parse_qs(urlparse(sender.reset_url).query)["token"][0]
            stored = await db.scalar(select(PasswordResetToken))
            assert stored is not None
            assert stored.token_digest != raw_token

            await service.reset(raw_token, "new-password-456")
            await db.refresh(user)
            assert verify_password("new-password-456", user.password_hash)
            assert await db.scalar(select(func.count()).select_from(UserSession)) == 0

            with pytest.raises(InvalidPasswordResetTokenError):
                await service.reset(raw_token, "third-password-789")
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_auth_rate_limit_hashes_identifiers_and_returns_retry_delay() -> None:
    engine, factory = _database()
    try:
        with factory() as session:
            db = AsyncSessionAdapter(session)
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/v1/auth/login",
                    "headers": [],
                    "client": ("203.0.113.10", 50000),
                    "server": ("test", 80),
                    "scheme": "http",
                    "query_string": b"",
                }
            )
            limiter = AuthRateLimiter(db, get_settings())  # type: ignore[arg-type]
            await limiter.check(
                "login", request, subject="Investor", ip_limit=2, subject_limit=2
            )
            await limiter.check(
                "login", request, subject="Investor", ip_limit=2, subject_limit=2
            )

            with pytest.raises(AuthRateLimitExceeded) as captured:
                await limiter.check(
                    "login", request, subject="Investor", ip_limit=2, subject_limit=2
                )

            assert captured.value.retry_after_seconds > 0
            events = list(await db.scalars(select(AuthRateLimitEvent)))
            assert len(events) == 2
            assert all(event.ip_digest != "203.0.113.10" for event in events)
            assert all(event.subject_digest != "investor" for event in events)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_account_export_omits_credentials_password_and_error_details() -> None:
    engine, factory = _database()
    try:
        with factory() as session:
            db = AsyncSessionAdapter(session)
            user = User(
                username="export-user",
                email="export@example.com",
                password_hash=hash_password("export-password-123"),
            )
            db.add(user)
            await db.flush()
            db.add(
                BrokerConnection(
                    user_id=user.id,
                    broker=Broker.TRADING212,
                    encrypted_credentials=b"never-export-this",
                    credential_hint="ending 1234",
                    status=ConnectionStatus.ERROR,
                    last_error="provider detail should remain private",
                )
            )
            await db.commit()

            exported = await AccountDataService(db).export(  # type: ignore[arg-type]
                user, "export-password-123"
            )

            assert exported["format"] == "northstar-account-export-v1"
            assert "password_hash" not in exported["account"]
            assert len(exported["connections"]) == 1
            assert "encrypted_credentials" not in exported["connections"][0]
            assert "last_error" not in exported["connections"][0]
            assert "never-export-this" not in str(exported)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_only_active_administrator_cannot_delete_their_account() -> None:
    engine, factory = _database()
    try:
        with factory() as session:
            db = AsyncSessionAdapter(session)
            admin = User(
                username="sole-admin",
                password_hash=hash_password("admin-password-123"),
                is_admin=True,
            )
            db.add(admin)
            await db.commit()

            with pytest.raises(LastAdministratorError):
                await AccountDataService(db).delete(  # type: ignore[arg-type]
                    admin, "admin-password-123"
                )

            assert await db.get(User, admin.id) is admin
    finally:
        engine.dispose()
