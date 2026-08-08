"""Add canonical instruments and provider aliases.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identity_key", sa.String(180), nullable=False, unique=True),
        sa.Column("canonical_symbol", sa.String(48), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("asset_type", sa.String(24), nullable=False),
        sa.Column("isin", sa.String(12), nullable=True, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_instruments_canonical_symbol", "instruments", ["canonical_symbol"])
    op.create_index("ix_instruments_asset_type", "instruments", ["asset_type"])

    op.create_table(
        "instrument_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("provider_instrument_id", sa.String(120), nullable=False),
        sa.Column("provider_symbol", sa.String(48), nullable=False),
        sa.Column("provider_name", sa.String(240), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "broker", "provider_instrument_id", name="uq_broker_instrument_alias"
        ),
    )
    op.create_index("ix_instrument_aliases_instrument_id", "instrument_aliases", ["instrument_id"])
    op.create_index("ix_instrument_aliases_broker", "instrument_aliases", ["broker"])

    op.add_column("positions", sa.Column("canonical_instrument_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_positions_canonical_instrument_id",
        "positions",
        "instruments",
        ["canonical_instrument_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_positions_canonical_instrument_id", "positions", ["canonical_instrument_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_positions_canonical_instrument_id", table_name="positions")
    op.drop_constraint(
        "fk_positions_canonical_instrument_id", "positions", type_="foreignkey"
    )
    op.drop_column("positions", "canonical_instrument_id")
    op.drop_table("instrument_aliases")
    op.drop_table("instruments")
