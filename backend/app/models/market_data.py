import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FxRate(Base):
    """A dated reference rate quoted as units of quote currency per one base currency."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "rate_date",
            "base_currency",
            "quote_currency",
            name="uq_fx_rate_source_date_pair",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String(32))
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    base_currency: Mapped[str] = mapped_column(String(12))
    quote_currency: Mapped[str] = mapped_column(String(12), index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class HistoricalPrice(Base):
    """Cached end-of-week market close for a canonical instrument."""

    __tablename__ = "historical_prices"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "price_date", "source", name="uq_historical_price_point"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        index=True,
    )
    price_date: Mapped[date] = mapped_column(Date, index=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    currency: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(16), default="weekly")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
