"""Add password recovery, auth throttling, and operational job monitoring.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index(
        "ix_password_reset_tokens_token_digest",
        "password_reset_tokens",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"]
    )

    op.create_table(
        "auth_rate_limit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("ip_digest", sa.String(64), nullable=False),
        sa.Column("subject_digest", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_auth_rate_action_ip_created",
        "auth_rate_limit_events",
        ["action", "ip_digest", "created_at"],
    )
    op.create_index(
        "ix_auth_rate_action_subject_created",
        "auth_rate_limit_events",
        ["action", "subject_digest", "created_at"],
    )
    op.create_index(
        "ix_auth_rate_limit_events_created_at",
        "auth_rate_limit_events",
        ["created_at"],
    )

    op.create_table(
        "operational_job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("safe_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_operational_job_runs_job_name", "operational_job_runs", ["job_name"])
    op.create_index("ix_operational_job_runs_status", "operational_job_runs", ["status"])
    op.create_index(
        "ix_operational_job_runs_started_at", "operational_job_runs", ["started_at"]
    )


def downgrade() -> None:
    op.drop_table("operational_job_runs")
    op.drop_table("auth_rate_limit_events")
    op.drop_table("password_reset_tokens")
