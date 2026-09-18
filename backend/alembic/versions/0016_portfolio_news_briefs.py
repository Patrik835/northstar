"""Add cached portfolio-aware daily news briefs.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_news_briefs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brief_date", sa.Date(), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("news_hash", sa.String(64), nullable=False),
        sa.Column("positions_count", sa.Integer(), nullable=False),
        sa.Column("selected_news_ids", sa.JSON(), nullable=False),
        sa.Column("highlights", sa.JSON(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "brief_date",
            "context_hash",
            "news_hash",
            name="uq_portfolio_news_brief_input",
        ),
    )
    op.create_index("ix_portfolio_news_briefs_user_id", "portfolio_news_briefs", ["user_id"])
    op.create_index("ix_portfolio_news_briefs_brief_date", "portfolio_news_briefs", ["brief_date"])
    op.create_index(
        "ix_portfolio_news_briefs_generated_at", "portfolio_news_briefs", ["generated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_news_briefs_generated_at", table_name="portfolio_news_briefs")
    op.drop_index("ix_portfolio_news_briefs_brief_date", table_name="portfolio_news_briefs")
    op.drop_index("ix_portfolio_news_briefs_user_id", table_name="portfolio_news_briefs")
    op.drop_table("portfolio_news_briefs")
