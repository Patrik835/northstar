"""Initial multi-tenant investment schema.

Revision ID: 0001
Revises: None
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username"), sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("goals", sa.Text()), sa.Column("risk_tolerance", sa.Integer()),
        sa.Column("time_horizon_years", sa.Integer()),
        sa.CheckConstraint("risk_tolerance between 1 and 5", name="ck_profile_risk_range"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_agent_hash", sa.LargeBinary()), sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_digest", "user_sessions", ["token_digest"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column("credential_hint", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "broker", name="uq_user_broker"),
    )
    op.create_index("ix_broker_connections_user_id", "broker_connections", ["user_id"])
    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("broker_connection_id", sa.Uuid(), sa.ForeignKey("broker_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.String(120), nullable=False), sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200)), sa.Column("asset_type", sa.String(24), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False), sa.Column("average_price", sa.Numeric(20, 8)),
        sa.Column("current_value", sa.Numeric(20, 4), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("current_value_eur", sa.Numeric(20, 4), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("broker_connection_id", "instrument_id", name="uq_position_instrument"),
    )
    op.create_index("ix_positions_broker_connection_id", "positions", ["broker_connection_id"])
    op.create_index("ix_positions_ticker", "positions", ["ticker"])
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("broker_connection_id", sa.Uuid(), sa.ForeignKey("broker_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False), sa.Column("total_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("total_value_eur", sa.Numeric(20, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("broker_connection_id", "snapshot_date", name="uq_connection_snapshot_date"),
    )
    op.create_index("ix_portfolio_snapshots_broker_connection_id", "portfolio_snapshots", ["broker_connection_id"])
    op.create_index("ix_portfolio_snapshots_snapshot_date", "portfolio_snapshots", ["snapshot_date"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("broker_connection_id", sa.Uuid(), sa.ForeignKey("broker_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False), sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("transaction_type", sa.String(24), nullable=False), sa.Column("quantity", sa.Numeric(28, 10)),
        sa.Column("price", sa.Numeric(20, 8)), sa.Column("value", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("broker_connection_id", "external_id", name="uq_transaction_external"),
    )
    op.create_index("ix_transactions_broker_connection_id", "transactions", ["broker_connection_id"])
    op.create_index("ix_transactions_ticker", "transactions", ["ticker"])
    op.create_index("ix_transactions_executed_at", "transactions", ["executed_at"])
    op.create_table(
        "news_items",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("external_id", sa.String(160), nullable=False, unique=True),
        sa.Column("ticker", sa.String(32), nullable=False), sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.String(120), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
    )
    op.create_index("ix_news_items_ticker", "news_items", ["ticker"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_table(
        "news_item_users",
        sa.Column("news_item_id", sa.Uuid(), sa.ForeignKey("news_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "ai_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_recommendations_user_id", "ai_recommendations", ["user_id"])
    op.create_index("ix_ai_recommendations_generated_at", "ai_recommendations", ["generated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    for table in ["chat_messages", "ai_recommendations", "news_item_users", "news_items", "transactions", "portfolio_snapshots", "positions", "broker_connections", "user_sessions", "user_profiles", "users"]:
        op.drop_table(table)

