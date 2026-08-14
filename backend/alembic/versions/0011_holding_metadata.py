"""Add user metadata for consolidated holdings.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holding_metadata",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("holding_key", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=True),
        sa.Column("tags_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("target_allocation_percentage", sa.Numeric(6, 3), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "holding_key", name="uq_user_holding_metadata"),
    )
    op.create_index(
        op.f("ix_holding_metadata_user_id"), "holding_metadata", ["user_id"]
    )
    op.execute(
        "UPDATE transactions SET value_eur = value "
        "WHERE UPPER(currency) = 'EUR' AND value_eur IS NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_holding_metadata_user_id"), table_name="holding_metadata")
    op.drop_table("holding_metadata")
