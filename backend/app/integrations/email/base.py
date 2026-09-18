from abc import ABC, abstractmethod


class EmailDeliveryError(Exception):
    """A sanitized email delivery failure safe to expose to the service layer."""


class EmailSender(ABC):
    @abstractmethod
    async def send_verification_email(
        self, *, recipient: str, username: str, verification_url: str
    ) -> None: ...

    async def send_notification_digest(
        self,
        *,
        recipient: str,
        username: str,
        alerts: list[str],
        news: list[str],
        events: list[str],
        updates_url: str,
    ) -> None:
        raise NotImplementedError

    async def send_password_reset_email(
        self,
        *,
        recipient: str,
        username: str,
        reset_url: str,
        expires_minutes: int,
    ) -> None:
        raise NotImplementedError
