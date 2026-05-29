"""initial storage foundation

Revision ID: 0001_initial_storage_foundation
Revises:
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_storage_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), server_default="info", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "trading_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("trading_mode", sa.String(length=20), server_default="OFF", nullable=False),
        sa.Column("live_armed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("kill_switch_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_date", name="uq_trading_sessions_session_date"),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kite_instrument_token", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=False),
        sa.Column("tradingsymbol", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("instrument_type", sa.String(length=50), nullable=False),
        sa.Column("tick_size", sa.Numeric(12, 4), nullable=False),
        sa.Column("lot_size", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_tradingsymbol"),
        sa.UniqueConstraint("kite_instrument_token", name="uq_instruments_kite_instrument_token"),
    )
    op.create_table(
        "candles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("high_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("low_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("close_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_candles_instrument_id_instruments"),
        sa.UniqueConstraint("instrument_id", "timeframe", "started_at", name="uq_candles_identity"),
    )
    op.create_index(
        "ix_candles_instrument_timeframe_started",
        "candles",
        ["instrument_id", "timeframe", "started_at"],
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("strategy_name", sa.String(length=100), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("features", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_signals_instrument_id_instruments"),
    )
    op.create_index("ix_signals_instrument_signal_time", "signals", ["instrument_id", "signal_time"])
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("model_run_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name="fk_recommendations_signal_id_signals"),
    )
    op.create_table(
        "risk_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("checks", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name="fk_risk_checks_recommendation_id_recommendations",
        ),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("risk_check_id", sa.Integer(), nullable=True),
        sa.Column("broker_order_id", sa.String(length=100), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("order_type", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_orders_quantity_positive")),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_orders_instrument_id_instruments"),
        sa.ForeignKeyConstraint(["risk_check_id"], ["risk_checks.id"], name="fk_orders_risk_check_id_risk_checks"),
        sa.UniqueConstraint("broker_order_id", name="uq_orders_broker_order_id"),
    )
    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("broker_status", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_order_events_order_id_orders"),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_order_id", sa.Integer(), nullable=True),
        sa.Column("exit_order_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("exit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_trades_quantity_positive")),
        sa.ForeignKeyConstraint(["entry_order_id"], ["orders.id"], name="fk_trades_entry_order_id_orders"),
        sa.ForeignKeyConstraint(["exit_order_id"], ["orders.id"], name="fk_trades_exit_order_id_orders"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_trades_instrument_id_instruments"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_type", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_journal_entries_created_at", "journal_entries", ["created_at"])
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_runs")
    op.drop_index("ix_journal_entries_created_at", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_table("trades")
    op.drop_table("order_events")
    op.drop_table("orders")
    op.drop_table("risk_checks")
    op.drop_table("recommendations")
    op.drop_index("ix_signals_instrument_signal_time", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_candles_instrument_timeframe_started", table_name="candles")
    op.drop_table("candles")
    op.drop_table("instruments")
    op.drop_table("trading_sessions")
    op.drop_table("system_events")
