from abc import ABC, abstractmethod


class EmailDeliveryError(Exception):
    """A sanitized email delivery failure safe to expose to the service layer."""


class EmailSender(ABC):
    @abstractmethod
    async def send_verification_email(
        self, *, recipient: str, username: str, verification_url: str
    ) -> None: ...

