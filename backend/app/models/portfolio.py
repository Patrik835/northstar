import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssetType, TransactionType

if TYPE_CHECKING:
    from app.models.instrument import Instrument


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("broker_connection_id", "instrument_id", name="uq_position_instrument"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_connections.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[str] = mapped_column(String(120))
    canonical_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, native_enum=False, length=24))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(12))
    current_value_eur: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    reported_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    reported_pnl_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    valued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    valuation_source: Mapped[str] = mapped_column(
        String(32), default="provider", server_default="provider"
    )
    is_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    connection: Mapped["BrokerConnection"] = relationship(back_populates="positions")
    canonical_instrument: Mapped["Instrument | None"] = relationship(
        back_populates="positions"
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "broker_connection_id", "snapshot_date", name="uq_connection_snapshot_date"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_connections.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(12))
    total_value_eur: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    reported_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    reported_pnl_eur: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    connection: Mapped["BrokerConnection"] = relationship(back_populates="snapshots")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("broker_connection_id", "external_id", name="uq_transaction_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_connections.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(160))
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, length=24)
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    value_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(12))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    connection: Mapped["BrokerConnection"] = relationship(back_populates="transactions")


class HoldingMetadata(Base):
    """User-owned annotations for a consolidated holding presentation key."""

    __tablename__ = "holding_metadata"
    __table_args__ = (
        UniqueConstraint("user_id", "holding_key", name="uq_user_holding_metadata"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    holding_key: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_allocation_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


from app.models.broker import BrokerConnection  # noqa: E402
