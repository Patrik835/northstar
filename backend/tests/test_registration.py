from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base
from app.integrations.email.base import EmailSender
from app.models.user import EmailVerificationToken, User
from app.schemas.auth import RegistrationRequest
from app.services.registration import RegistrationService


class CapturingEmailSender(EmailSender):
    def __init__(self) -> None:
        self.message: dict[str, str] | None = None

    async def send_verification_email(
        self, *, recipient: str, username: str, verification_url: str
    ) -> None:
        self.message = {
            "recipient": recipient,
            "username": username,
            "verification_url": verification_url,
        }


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item) -> None:
        self.session.add(item)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)


def test_registration_rejects_mismatched_passwords() -> None:
    with pytest.raises(ValidationError, match="Passwords do not match"):
        RegistrationRequest(
            username="investor",
            email="investor@example.com",
            password="a-secure-password",
            password_confirmation="a-different-password",
        )


def test_registration_explains_invalid_username_in_plain_language() -> None:
    with pytest.raises(
        ValidationError,
        match="Username can only contain letters, numbers, dots, underscores, and hyphens",
    ):
        RegistrationRequest(
            username="basic person",
            email="investor@example.com",
            password="a-secure-password",
            password_confirmation="a-secure-password",
        )


async def test_verification_delivery_contains_raw_token_only_in_link() -> None:
    sender = CapturingEmailSender()
    service = RegistrationService(None, get_settings(), sender)  # type: ignore[arg-type]
    user = User(
        username="investor",
        email="investor@example.com",
        password_hash="not-used-in-this-unit-test",
    )

    await service._deliver(user, "one-time-secret")

    assert sender.message is not None
    assert sender.message["recipient"] == "investor@example.com"
    parsed = urlparse(sender.message["verification_url"])
    assert parsed.path == "/verify-email"
    assert parse_qs(parsed.query) == {"token": ["one-time-secret"]}


@pytest.mark.asyncio
async def test_existing_account_can_add_email_and_receive_verification() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            user = User(username="existing-user", password_hash="unused")
            db.add(user)
            await db.commit()
            sender = CapturingEmailSender()

            await RegistrationService(
                db,  # type: ignore[arg-type]
                get_settings(),
                sender,
            ).set_account_email(user, " Investor@Example.com ")

            assert user.email == "investor@example.com"
            assert user.email_verified_at is None
            assert sender.message is not None
            assert sender.message["recipient"] == "investor@example.com"
            assert await db.scalar(select(func.count()).select_from(EmailVerificationToken)) == 1
    finally:
        engine.dispose()


def _registration_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_first_account_becomes_active_admin_without_email() -> None:
    engine, factory = _registration_db()
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            sender = CapturingEmailSender()
            service = RegistrationService(db, get_settings(), sender)  # type: ignore[arg-type]

            assert await service.needs_setup() is True
            assert await service.register("owner", "owner@example.com", "x" * 12) is True

            owner = sync_db.scalar(select(User).where(User.username == "owner"))
            assert owner is not None and owner.is_admin and owner.email_verified_at
            assert sender.message is None
            assert await service.needs_setup() is False

            assert await service.register("guest", "guest@example.com", "x" * 12) is False
            guest = sync_db.scalar(select(User).where(User.username == "guest"))
            assert guest is not None and not guest.is_admin and guest.email_verified_at is None
            assert sender.message is not None
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_first_account_is_allowed_even_when_public_signup_is_disabled() -> None:
    from app.services.registration import SignupDisabledError

    engine, factory = _registration_db()
    settings = get_settings().model_copy(update={"public_signup_enabled": False})
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            service = RegistrationService(db, settings, CapturingEmailSender())  # type: ignore[arg-type]
            assert await service.register("owner", "owner@example.com", "x" * 12) is True
            with pytest.raises(SignupDisabledError):
                await service.register("guest", "guest@example.com", "x" * 12)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_without_email_server_new_accounts_are_active_immediately() -> None:
    engine, factory = _registration_db()
    settings = get_settings().model_copy(update={"smtp_host": ""})
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            sender = CapturingEmailSender()
            service = RegistrationService(db, settings, sender)  # type: ignore[arg-type]
            await service.register("owner", "owner@example.com", "x" * 12)
            assert await service.register("guest", "guest@example.com", "x" * 12) is True
            guest = sync_db.scalar(select(User).where(User.username == "guest"))
            assert guest is not None and guest.email_verified_at is not None
            assert sender.message is None
    finally:
        engine.dispose()
