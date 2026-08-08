"""Track connection attempts and last successful synchronization.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "broker_connections",
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_connections",
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE broker_connections
        SET last_sync_attempt_at = last_synced_at,
            last_successful_sync_at = last_synced_at
        WHERE last_synced_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("broker_connections", "last_successful_sync_at")
    op.drop_column("broker_connections", "last_sync_attempt_at")
