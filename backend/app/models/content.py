import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import ChatRole

news_item_users = Table(
    "news_item_users",
    Base.metadata,
    Column(
        "news_item_id",
        UUID(as_uuid=True),
        ForeignKey("news_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(160), unique=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    headline: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str] = mapped_column(Text)


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, native_enum=False, length=16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
