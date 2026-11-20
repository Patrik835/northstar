"""Remove retired exchange purchase-cost storage; restore schema on downgrade.

Data restoration requires the pre-migration database backup.
"""
import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("position_cost_bases")


def downgrade() -> None:
    op.create_table(
        "position_cost_bases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("broker_connection_id", sa.UUID(), nullable=False),
        sa.Column("instrument_id", sa.String(120), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("average_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_eur", sa.Numeric(20, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["broker_connection_id"], ["broker_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_connection_id", "instrument_id", name="uq_position_cost_basis"),
    )
    op.create_index(
        "ix_position_cost_bases_broker_connection_id",
        "position_cost_bases",
        ["broker_connection_id"],
    )

