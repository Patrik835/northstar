"""Add persisted ECB FX rates and observable connection sync runs.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("base_currency", sa.String(12), nullable=False),
        sa.Column("quote_currency", sa.String(12), nullable=False),
        sa.Column("rate", sa.Numeric(28, 12), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source",
            "rate_date",
            "base_currency",
            "quote_currency",
            name="uq_fx_rate_source_date_pair",
        ),
    )
    op.create_index("ix_fx_rates_rate_date", "fx_rates", ["rate_date"])
    op.create_index("ix_fx_rates_quote_currency", "fx_rates", ["quote_currency"])
    op.create_index("ix_fx_rates_fetched_at", "fx_rates", ["fetched_at"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "broker_connection_id",
            sa.Uuid(),
            sa.ForeignKey("broker_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("positions_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transactions_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transactions_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safe_error_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sync_runs_broker_connection_id", "sync_runs", ["broker_connection_id"]
    )
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"])


def downgrade() -> None:
    op.drop_table("sync_runs")
    op.drop_table("fx_rates")
