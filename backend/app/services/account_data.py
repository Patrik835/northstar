from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.broker import BrokerConnection
from app.models.content import (
    AIRecommendation,
    Alert,
    ChatMessage,
    Conversation,
    NewsReadState,
    NotificationPreference,
    PortfolioContextSnapshot,
    PortfolioNewsBrief,
    calendar_event_users,
    news_item_users,
)
from app.models.portfolio import HoldingMetadata, PortfolioSnapshot, Position, Transaction
from app.models.user import User, UserProfile


class AccountPasswordError(Exception):
    pass


class LastAdministratorError(Exception):
    pass


def _columns(row: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    blocked = exclude or set()
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in blocked
    }


class AccountDataService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def export(self, user: User, current_password: str) -> dict[str, Any]:
        self._verify(user, current_password)
        connections = list(
            await self.db.scalars(
                select(BrokerConnection).where(BrokerConnection.user_id == user.id)
            )
        )
        connection_ids = [item.id for item in connections]

        async def owned_rows(model: Any, key: str = "user_id") -> list[Any]:
            return list(
                await self.db.scalars(select(model).where(getattr(model, key) == user.id))
            )

        async def connection_rows(model: Any) -> list[Any]:
            if not connection_ids:
                return []
            return list(
                await self.db.scalars(
                    select(model).where(model.broker_connection_id.in_(connection_ids))
                )
            )

        profile = await self.db.get(UserProfile, user.id)
        news_links = list(
            await self.db.scalars(
                select(news_item_users.c.news_item_id).where(news_item_users.c.user_id == user.id)
            )
        )
        calendar_links = list(
            await self.db.scalars(
                select(calendar_event_users.c.calendar_event_id).where(
                    calendar_event_users.c.user_id == user.id
                )
            )
        )
        payload = {
            "format": "northstar-account-export-v1",
            "account": _columns(
                user,
                exclude={
                    "password_hash",
                    "failed_login_attempts",
                    "locked_until",
                },
            ),
            "profile": _columns(profile) if profile else None,
            "connections": [
                _columns(item, exclude={"encrypted_credentials", "last_error"})
                for item in connections
            ],
            "positions": [_columns(item) for item in await connection_rows(Position)],
            "transactions": [_columns(item) for item in await connection_rows(Transaction)],
            "portfolio_snapshots": [
                _columns(item) for item in await connection_rows(PortfolioSnapshot)
            ],
            "holding_metadata": [
                _columns(item) for item in await owned_rows(HoldingMetadata)
            ],
            "alerts": [_columns(item) for item in await owned_rows(Alert)],
            "notification_preferences": [
                _columns(item) for item in await owned_rows(NotificationPreference)
            ],
            "news_read_states": [
                _columns(item) for item in await owned_rows(NewsReadState)
            ],
            "linked_news_item_ids": news_links,
            "linked_calendar_event_ids": calendar_links,
            "ai_recommendations": [
                _columns(item) for item in await owned_rows(AIRecommendation)
            ],
            "portfolio_context_snapshots": [
                _columns(item) for item in await owned_rows(PortfolioContextSnapshot)
            ],
            "portfolio_news_briefs": [
                _columns(item) for item in await owned_rows(PortfolioNewsBrief)
            ],
            "conversations": [_columns(item) for item in await owned_rows(Conversation)],
            "chat_messages": [_columns(item) for item in await owned_rows(ChatMessage)],
        }
        return jsonable_encoder(payload)

    async def delete(self, user: User, current_password: str) -> None:
        self._verify(user, current_password)
        if user.is_admin:
            admin_count = await self.db.scalar(
                select(func.count()).select_from(User).where(
                    User.is_admin.is_(True), User.is_active.is_(True)
                )
            )
            if int(admin_count or 0) <= 1:
                raise LastAdministratorError
        await self.db.delete(user)
        await self.db.commit()

    @staticmethod
    def _verify(user: User, current_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AccountPasswordError
