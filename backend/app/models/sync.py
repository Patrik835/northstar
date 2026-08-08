import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import SyncRunStatus, SyncTrigger

if TYPE_CHECKING:
    from app.models.broker import BrokerConnection


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("broker_connections.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[SyncRunStatus] = mapped_column(
        Enum(
            SyncRunStatus,
            native_enum=False,
            length=24,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=SyncRunStatus.RUNNING,
        index=True,
    )
    trigger: Mapped[SyncTrigger] = mapped_column(
        Enum(
            SyncTrigger,
            native_enum=False,
            length=24,
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    positions_written: Mapped[int] = mapped_column(Integer, default=0)
    transactions_read: Mapped[int] = mapped_column(Integer, default=0)
    transactions_written: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    safe_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    connection: Mapped["BrokerConnection"] = relationship(back_populates="sync_runs")


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint(
            "broker_connection_id", "stream", name="uq_sync_cursor_connection_stream"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("broker_connections.id", ondelete="CASCADE"),
        index=True,
    )
    stream: Mapped[str] = mapped_column(String(32))
    next_page_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    connection: Mapped["BrokerConnection"] = relationship(back_populates="sync_cursors")
