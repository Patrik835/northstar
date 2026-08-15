import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssetType, Broker

if TYPE_CHECKING:
    from app.models.portfolio import Position


class Instrument(Base):
    """A provider-independent asset held through one or more connections."""

    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    identity_key: Mapped[str] = mapped_column(String(180), unique=True)
    canonical_symbol: Mapped[str] = mapped_column(String(48), index=True)
    name: Mapped[str] = mapped_column(String(240))
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, native_enum=False, length=24), index=True
    )
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    metadata_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    aliases: Mapped[list["InstrumentAlias"]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(back_populates="canonical_instrument")


class InstrumentAlias(Base):
    """A broker's stable identifier and display symbol for a canonical instrument."""

    __tablename__ = "instrument_aliases"
    __table_args__ = (
        UniqueConstraint("broker", "provider_instrument_id", name="uq_broker_instrument_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        index=True,
    )
    broker: Mapped[Broker] = mapped_column(
        Enum(Broker, native_enum=False, length=32), index=True
    )
    provider_instrument_id: Mapped[str] = mapped_column(String(120))
    provider_symbol: Mapped[str] = mapped_column(String(48))
    provider_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    instrument: Mapped[Instrument] = relationship(back_populates="aliases")
