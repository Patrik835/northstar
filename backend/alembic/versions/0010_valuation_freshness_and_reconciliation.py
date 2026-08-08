"""Persist position valuation provenance and source reconciliation results.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column(
            "valued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.add_column(
        "positions",
        sa.Column(
            "valuation_source",
            sa.String(32),
            server_default="provider",
            nullable=True,
        ),
    )
    op.add_column(
        "positions",
        sa.Column("is_estimated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        "UPDATE positions SET valued_at = updated_at, valuation_source = 'provider'"
    )
    op.alter_column("positions", "valued_at", nullable=False)
    op.alter_column("positions", "valuation_source", nullable=False)

    op.add_column(
        "broker_connections",
        sa.Column("reconciliation_difference_percent", sa.Numeric(9, 4), nullable=True),
    )
    op.add_column(
        "broker_connections",
        sa.Column("reconciliation_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_connections",
        sa.Column("reconciliation_warning", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("broker_connections", "reconciliation_warning")
    op.drop_column("broker_connections", "reconciliation_checked_at")
    op.drop_column("broker_connections", "reconciliation_difference_percent")
    op.drop_column("positions", "is_estimated")
    op.drop_column("positions", "valuation_source")
    op.drop_column("positions", "valued_at")
