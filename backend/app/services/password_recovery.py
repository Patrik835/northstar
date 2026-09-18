import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.security import digest_session_token, hash_password
from app.integrations.email.base import EmailSender
from app.models.user import PasswordResetToken, UserSession
from app.repositories.users import UserRepository


class InvalidPasswordResetTokenError(Exception):
    pass


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class PasswordRecoveryService:
    def __init__(self, db: AsyncSession, settings: Settings, email_sender: EmailSender) -> None:
        self.db = db
        self.settings = settings
        self.email_sender = email_sender
        self.users = UserRepository(db)

    async def request(self, email: str) -> None:
        user = await self.users.by_email(email.strip().lower())
        if not user or not user.email or not user.is_active:
            return
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw_token = secrets.token_urlsafe(48)
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                token_digest=digest_session_token(raw_token),
                expires_at=now + timedelta(minutes=self.settings.password_reset_ttl_minutes),
            )
        )
        await self.db.commit()
        query = urlencode({"token": raw_token})
        await self.email_sender.send_password_reset_email(
            recipient=user.email,
            username=user.username,
            reset_url=f"{self.settings.public_web_url.rstrip('/')}/reset-password?{query}",
            expires_minutes=self.settings.password_reset_ttl_minutes,
        )

    async def reset(self, raw_token: str, new_password: str) -> None:
        now = datetime.now(timezone.utc)
        token = await self.db.scalar(
            select(PasswordResetToken)
            .options(selectinload(PasswordResetToken.user))
            .where(PasswordResetToken.token_digest == digest_session_token(raw_token))
        )
        if (
            not token
            or token.used_at
            or _as_utc(token.expires_at) <= now
            or not token.user.is_active
        ):
            raise InvalidPasswordResetTokenError
        token.user.password_hash = hash_password(new_password)
        token.user.failed_login_attempts = 0
        token.user.locked_until = None
        await self.db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == token.user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.db.execute(delete(UserSession).where(UserSession.user_id == token.user_id))
        await self.db.commit()
