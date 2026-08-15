"""Add portfolio analytics metadata and benchmark settings.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("instruments", sa.Column("sector", sa.String(120), nullable=True))
    op.add_column("instruments", sa.Column("industry", sa.String(160), nullable=True))
    op.add_column("instruments", sa.Column("country", sa.String(120), nullable=True))
    op.add_column("instruments", sa.Column("metadata_source", sa.String(32), nullable=True))
    op.add_column(
        "instruments", sa.Column("metadata_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_instruments_sector"), "instruments", ["sector"])
    op.create_index(op.f("ix_instruments_country"), "instruments", ["country"])
    op.add_column(
        "user_profiles", sa.Column("benchmark_instrument_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_user_profiles_benchmark_instrument",
        "user_profiles",
        "instruments",
        ["benchmark_instrument_id"],
        ["id"],
        ondelete="SET NULL",
    )
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
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "exposure_type",
            "label",
            "source",
            name="uq_instrument_exposure",
        ),
    )
    op.create_index(
        op.f("ix_instrument_exposures_instrument_id"),
        "instrument_exposures",
        ["instrument_id"],
    )
    op.create_index(
        op.f("ix_instrument_exposures_exposure_type"),
        "instrument_exposures",
        ["exposure_type"],
    )
    op.create_index(
        op.f("ix_instrument_exposures_fetched_at"),
        "instrument_exposures",
        ["fetched_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_instrument_exposures_fetched_at"), table_name="instrument_exposures")
    op.drop_index(
        op.f("ix_instrument_exposures_exposure_type"), table_name="instrument_exposures"
    )
    op.drop_index(
        op.f("ix_instrument_exposures_instrument_id"), table_name="instrument_exposures"
    )
    op.drop_table("instrument_exposures")
    op.drop_constraint(
        "fk_user_profiles_benchmark_instrument", "user_profiles", type_="foreignkey"
    )
    op.drop_column("user_profiles", "benchmark_instrument_id")
    op.drop_index(op.f("ix_instruments_country"), table_name="instruments")
    op.drop_index(op.f("ix_instruments_sector"), table_name="instruments")
    op.drop_column("instruments", "metadata_updated_at")
    op.drop_column("instruments", "metadata_source")
    op.drop_column("instruments", "country")
    op.drop_column("instruments", "industry")
    op.drop_column("instruments", "sector")
