"""Remove ETF look-through storage.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("instrument_exposures")


def downgrade() -> None:
    op.create_table(
        "instrument_exposures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("instrument_id", sa.UUID(), nullable=False),
        sa.Column("exposure_type", sa.String(24), nullable=False),
        sa.Column("label", sa.String(240), nullable=False),
        sa.Column("symbol", sa.String(48), nullable=True),
        sa.Column("weight_percentage", sa.Numeric(10, 6), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "exposure_type", "label", "source", name="uq_instrument_exposure"
        ),
    )
    op.create_index(
        op.f("ix_instrument_exposures_instrument_id"), "instrument_exposures", ["instrument_id"]
    )
    op.create_index(
        op.f("ix_instrument_exposures_exposure_type"), "instrument_exposures", ["exposure_type"]
    )
    op.create_index(
        op.f("ix_instrument_exposures_fetched_at"), "instrument_exposures", ["fetched_at"]
    )
