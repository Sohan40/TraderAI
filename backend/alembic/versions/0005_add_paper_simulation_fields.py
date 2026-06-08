"""add paper simulation fields

Revision ID: 0005_add_paper_simulation_fields
Revises: 0004_add_scanner_signal_fields
Create Date: 2026-06-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_add_paper_simulation_fields"
down_revision: str | None = "0004_add_scanner_signal_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("signal_id", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("simulated", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_foreign_key(
        "fk_orders_signal_id_signals",
        "orders",
        "signals",
        ["signal_id"],
        ["id"],
    )
    op.create_index("ix_orders_signal_simulated", "orders", ["signal_id", "simulated"])

    op.add_column("trades", sa.Column("signal_id", sa.Integer(), nullable=True))
    op.add_column(
        "trades",
        sa.Column("simulated", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("trades", sa.Column("gross_pnl", sa.Numeric(18, 6), nullable=True))
    op.add_column("trades", sa.Column("estimated_costs", sa.Numeric(18, 6), nullable=True))
    op.add_column("trades", sa.Column("net_pnl", sa.Numeric(18, 6), nullable=True))
    op.add_column("trades", sa.Column("exit_reason", sa.String(length=50), nullable=True))
    op.add_column("trades", sa.Column("paper_mode", sa.String(length=20), nullable=True))
    op.create_foreign_key(
        "fk_trades_signal_id_signals",
        "trades",
        "signals",
        ["signal_id"],
        ["id"],
    )
    op.create_index("ix_trades_signal_simulated", "trades", ["signal_id", "simulated"])
    op.create_index(
        "uq_trades_paper_signal_id",
        "trades",
        ["signal_id"],
        unique=True,
        postgresql_where=sa.text("simulated = true AND signal_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_trades_paper_signal_id", table_name="trades")
    op.drop_index("ix_trades_signal_simulated", table_name="trades")
    op.drop_constraint("fk_trades_signal_id_signals", "trades", type_="foreignkey")
    op.drop_column("trades", "paper_mode")
    op.drop_column("trades", "exit_reason")
    op.drop_column("trades", "net_pnl")
    op.drop_column("trades", "estimated_costs")
    op.drop_column("trades", "gross_pnl")
    op.drop_column("trades", "simulated")
    op.drop_column("trades", "signal_id")

    op.drop_index("ix_orders_signal_simulated", table_name="orders")
    op.drop_constraint("fk_orders_signal_id_signals", "orders", type_="foreignkey")
    op.drop_column("orders", "simulated")
    op.drop_column("orders", "signal_id")
