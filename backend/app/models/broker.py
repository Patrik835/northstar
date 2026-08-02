import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import Broker, ConnectionStatus

if TYPE_CHECKING:
    from app.models.portfolio import PortfolioSnapshot, Position, Transaction


class BrokerConnection(Base):
    __tablename__ = "broker_connections"
    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_user_broker"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    broker: Mapped[Broker] = mapped_column(Enum(Broker, native_enum=False, length=32))
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)
    credential_hint: Mapped[str] = mapped_column(String(32))
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, native_enum=False, length=32), default=ConnectionStatus.PENDING
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    positions: Mapped[list["Position"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
