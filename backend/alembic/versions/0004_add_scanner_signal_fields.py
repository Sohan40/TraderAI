"""add scanner signal fields

Revision ID: 0004_add_scanner_signal_fields
Revises: 0003_add_candle_source
Create Date: 2026-06-03 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_add_scanner_signal_fields"
down_revision: str | None = "0003_add_candle_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("strategy_version", sa.String(length=50), server_default="p05_v1", nullable=False),
    )
    op.add_column("signals", sa.Column("signal_key", sa.String(length=255), nullable=True))
    op.add_column(
        "signals",
        sa.Column(
            "signal_status",
            sa.String(length=30),
            server_default="REJECTED_SIGNAL",
            nullable=False,
        ),
    )
    op.add_column(
        "signals",
        sa.Column(
            "veto_reasons",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("signals", sa.Column("replay_run_id", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE signals
        SET signal_key = strategy_name || ':' || instrument_id::text || ':' ||
            to_char(signal_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
        WHERE signal_key IS NULL
        """
    )
    op.alter_column("signals", "signal_key", nullable=False)
    op.create_unique_constraint("uq_signals_signal_key", "signals", ["signal_key"])
    op.create_index("ix_signals_status_created_at", "signals", ["signal_status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_signals_status_created_at", table_name="signals")
    op.drop_constraint("uq_signals_signal_key", "signals", type_="unique")
    op.drop_column("signals", "replay_run_id")
    op.drop_column("signals", "veto_reasons")
    op.drop_column("signals", "signal_status")
    op.drop_column("signals", "signal_key")
    op.drop_column("signals", "strategy_version")
