"""Add resumable provider history cursors.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "broker_connection_id",
            sa.Uuid(),
            sa.ForeignKey("broker_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stream", sa.String(32), nullable=False),
        sa.Column("next_page_path", sa.Text(), nullable=True),
        sa.Column(
            "backfill_complete", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "broker_connection_id",
            "stream",
            name="uq_sync_cursor_connection_stream",
        ),
    )
    op.create_index(
        "ix_sync_cursors_broker_connection_id",
        "sync_cursors",
        ["broker_connection_id"],
    )


def downgrade() -> None:
    op.drop_table("sync_cursors")
