import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import digest_session_token, hash_password
from app.integrations.email.base import EmailSender
from app.models.user import EmailVerificationToken, User
from app.repositories.users import UserRepository


class SignupDisabledError(Exception):
    pass


class RegistrationConflictError(Exception):
    pass


class InvalidVerificationTokenError(Exception):
    pass


class RegistrationService:
    def __init__(
        self, db: AsyncSession, settings: Settings, email_sender: EmailSender
    ) -> None:
        self.db = db
        self.settings = settings
        self.email_sender = email_sender
        self.users = UserRepository(db)

    async def register(self, username: str, email: str, password: str) -> None:
        if not self.settings.public_signup_enabled:
            raise SignupDisabledError

        normalized_email = email.strip().lower()
        user = User(
            username=username.strip(),
            email=normalized_email,
            password_hash=hash_password(password),
            is_admin=False,
            email_verified_at=None,
        )
        self.db.add(user)
        try:
            await self.db.flush()
            raw_token = await self._new_token(user)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise RegistrationConflictError from exc

        await self._deliver(user, raw_token)

    async def verify(self, raw_token: str) -> None:
        now = datetime.now(timezone.utc)
        token = await self.users.verification_token(digest_session_token(raw_token))
        if not token or token.used_at or token.expires_at <= now:
            raise InvalidVerificationTokenError

        token.user.email_verified_at = now
        await self.db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == token.user_id,
                EmailVerificationToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.db.commit()

    async def resend(self, email: str) -> None:
        user = await self.users.by_email(email.strip().lower())
        if not user or user.email_verified_at or not user.email:
            return
        raw_token = await self._new_token(user)
        await self.db.commit()
        await self._deliver(user, raw_token)

    async def _new_token(self, user: User) -> str:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw_token = secrets.token_urlsafe(48)
        self.db.add(
            EmailVerificationToken(
                user_id=user.id,
                token_digest=digest_session_token(raw_token),
                expires_at=now
                + timedelta(hours=self.settings.email_verification_ttl_hours),
            )
        )
        return raw_token

    async def _deliver(self, user: User, raw_token: str) -> None:
        assert user.email is not None
        query = urlencode({"token": raw_token})
        verification_url = (
            f"{self.settings.public_web_url.rstrip('/')}/verify-email?{query}"
        )
        await self.email_sender.send_verification_email(
            recipient=user.email,
            username=user.username,
            verification_url=verification_url,
        )
