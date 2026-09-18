"""Add news read state, events, alerts, notification preferences, and grounded AI state.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_items", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("news_items", sa.Column("image_url", sa.Text(), nullable=True))
    op.create_table(
        "news_read_states",
        sa.Column(
            "news_item_id",
            sa.Uuid(),
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_id", sa.String(180), nullable=False, unique=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_calendar_events_ticker", "calendar_events", ["ticker"])
    op.create_index("ix_calendar_events_event_type", "calendar_events", ["event_type"])
    op.create_index("ix_calendar_events_event_date", "calendar_events", ["event_date"])
    op.create_table(
        "calendar_event_users",
        sa.Column(
            "calendar_event_id",
            sa.Uuid(),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("dedupe_key", sa.String(180), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_alert_user_key"),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("email_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("digest_frequency", sa.String(16), nullable=False, server_default="weekly"),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "portfolio_context_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "context_hash", name="uq_portfolio_context_user_hash"),
    )
    op.create_index(
        "ix_portfolio_context_snapshots_user_id", "portfolio_context_snapshots", ["user_id"]
    )
    op.create_index(
        "ix_portfolio_context_snapshots_calculated_at",
        "portfolio_context_snapshots",
        ["calculated_at"],
    )
    op.add_column("ai_recommendations", sa.Column("context_version", sa.String(40), nullable=True))
    op.add_column("ai_recommendations", sa.Column("context_hash", sa.String(64), nullable=True))
    op.add_column(
        "ai_recommendations",
        sa.Column("calculation_references", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_ai_recommendations_context_hash", "ai_recommendations", ["context_hash"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(120), nullable=False, server_default="Portfolio conversation"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_created_at", "conversations", ["created_at"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.add_column(
        "chat_messages",
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_column("chat_messages", "conversation_id")
    op.drop_table("conversations")
    op.drop_index("ix_ai_recommendations_context_hash", table_name="ai_recommendations")
    op.drop_column("ai_recommendations", "calculation_references")
    op.drop_column("ai_recommendations", "context_hash")
    op.drop_column("ai_recommendations", "context_version")
    op.drop_table("portfolio_context_snapshots")
    op.drop_table("notification_preferences")
    op.drop_table("alerts")
    op.drop_table("calendar_event_users")
    op.drop_table("calendar_events")
    op.drop_table("news_read_states")
    op.drop_column("news_items", "image_url")
    op.drop_column("news_items", "summary")
