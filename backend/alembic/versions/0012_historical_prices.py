"""Add cached historical instrument prices.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_prices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("instrument_id", sa.UUID(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("close_price", sa.Numeric(28, 10), nullable=False),
        sa.Column("currency", sa.String(12), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(16), server_default="weekly", nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "price_date", "source", name="uq_historical_price_point"
        ),
    )
    op.create_index(
        op.f("ix_historical_prices_instrument_id"),
        "historical_prices",
        ["instrument_id"],
    )
    op.create_index(
        op.f("ix_historical_prices_price_date"),
        "historical_prices",
        ["price_date"],
    )
    op.create_index(
        op.f("ix_historical_prices_fetched_at"),
        "historical_prices",
        ["fetched_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_historical_prices_fetched_at"), table_name="historical_prices")
    op.drop_index(op.f("ix_historical_prices_price_date"), table_name="historical_prices")
    op.drop_index(op.f("ix_historical_prices_instrument_id"), table_name="historical_prices")
    op.drop_table("historical_prices")
