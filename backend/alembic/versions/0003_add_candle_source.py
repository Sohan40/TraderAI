"""add candle source

Revision ID: 0003_add_candle_source
Revises: 0002_add_broker_sessions
Create Date: 2026-05-30 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_candle_source"
down_revision: str | None = "0002_add_broker_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candles",
        sa.Column(
            "source",
            sa.String(length=50),
            server_default="KITE_WEBSOCKET",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("candles", "source")
