"""Expand currency fields for crypto quote assets.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("positions", "portfolio_snapshots", "transactions"):
        op.alter_column(
            table,
            "currency",
            existing_type=sa.String(length=3),
            type_=sa.String(length=12),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in ("positions", "portfolio_snapshots", "transactions"):
        op.alter_column(
            table,
            "currency",
            existing_type=sa.String(length=12),
            type_=sa.String(length=3),
            existing_nullable=False,
        )
