import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint, func
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
