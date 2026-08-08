"""Persist broker-reported position and snapshot profit/loss.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "positions", sa.Column("reported_pnl", sa.Numeric(20, 4), nullable=True)
    )
    op.add_column(
        "positions", sa.Column("reported_pnl_eur", sa.Numeric(20, 4), nullable=True)
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("reported_pnl", sa.Numeric(20, 4), nullable=True),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("reported_pnl_eur", sa.Numeric(20, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("portfolio_snapshots", "reported_pnl_eur")
    op.drop_column("portfolio_snapshots", "reported_pnl")
    op.drop_column("positions", "reported_pnl_eur")
    op.drop_column("positions", "reported_pnl")
