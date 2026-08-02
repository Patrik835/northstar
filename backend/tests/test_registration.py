from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.integrations.email.base import EmailSender
from app.models.user import User
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
