import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import EmailVerificationToken, User, UserProfile, UserSession


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def by_username(self, username: str) -> User | None:
        return await self.db.scalar(select(User).where(User.username == username))

    async def by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.db.scalar(
            select(User).options(selectinload(User.profile)).where(User.id == user_id)
        )

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        return user

    async def session_user(self, token_digest: str, now: datetime) -> User | None:
        return await self.db.scalar(
            select(User)
            .join(UserSession)
            .where(
                UserSession.token_digest == token_digest,
                UserSession.expires_at > now,
                User.is_active.is_(True),
            )
        )

    async def profile(self, user_id: uuid.UUID) -> UserProfile | None:
        return await self.db.get(UserProfile, user_id)

    async def verification_token(
        self, token_digest: str
    ) -> EmailVerificationToken | None:
        return await self.db.scalar(
            select(EmailVerificationToken)
            .options(selectinload(EmailVerificationToken.user))
            .where(EmailVerificationToken.token_digest == token_digest)
        )
