from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    digest_session_token,
    hash_password,
    new_session_token,
    verify_password,
)
from app.models.user import User, UserSession
from app.repositories.users import UserRepository


class InvalidCredentialsError(Exception):
    pass


class AccountLockedError(Exception):
    pass


class EmailNotVerifiedError(Exception):
    pass


class AuthService:
    max_attempts = 5
    lockout_minutes = 15

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)

    async def login(self, username: str, password: str) -> tuple[User, str]:
        now = datetime.now(timezone.utc)
        user = await self.users.by_username(username)
        if user and user.locked_until and user.locked_until > now:
            raise AccountLockedError
        if not user or not verify_password(password, user.password_hash) or not user.is_active:
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= self.max_attempts:
                    user.locked_until = now + timedelta(minutes=self.lockout_minutes)
                    user.failed_login_attempts = 0
                await self.db.commit()
            raise InvalidCredentialsError

        if user.email and not user.email_verified_at:
            raise EmailNotVerifiedError

        user.failed_login_attempts = 0
        user.locked_until = None
        raw_token = new_session_token()
        self.db.add(
            UserSession(
                user_id=user.id,
                token_digest=digest_session_token(raw_token),
                expires_at=now + timedelta(hours=self.settings.session_ttl_hours),
            )
        )
        await self.db.commit()
        return user, raw_token

    async def logout(self, raw_token: str) -> None:
        await self.db.execute(
            delete(UserSession).where(UserSession.token_digest == digest_session_token(raw_token))
        )
        await self.db.commit()

    async def change_password(self, user: User, current: str, new: str) -> None:
        if not verify_password(current, user.password_hash):
            raise InvalidCredentialsError
        user.password_hash = hash_password(new)
        await self.db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        await self.db.commit()
