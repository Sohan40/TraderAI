"""add broker sessions

Revision ID: 0002_add_broker_sessions
Revises: 0001_initial_storage_foundation
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_broker_sessions"
down_revision: str | None = "0001_initial_storage_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broker_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_broker_sessions_broker_created_at",
        "broker_sessions",
        ["broker", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_broker_sessions_broker_created_at", table_name="broker_sessions")
    op.drop_table("broker_sessions")
