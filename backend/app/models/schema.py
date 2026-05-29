"""Initial SQLAlchemy table metadata for P01 storage foundation."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


system_events = Table(
    "system_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_type", String(100), nullable=False),
    Column("severity", String(20), nullable=False, server_default="info"),
    Column("message", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

trading_sessions = Table(
    "trading_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("session_date", Date, nullable=False, unique=True),
    Column("trading_mode", String(20), nullable=False, server_default="OFF"),
    Column("live_armed", Boolean, nullable=False, server_default="false"),
    Column("kill_switch_active", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

broker_sessions = Table(
    "broker_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("broker", String(50), nullable=False),
    Column("user_id", String(100), nullable=True),
    Column("status", String(50), nullable=False),
    Column("login_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("encrypted_access_token", Text, nullable=False),
    Column("invalidated_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

instruments = Table(
    "instruments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kite_instrument_token", String(64), nullable=False, unique=True),
    Column("exchange", String(20), nullable=False),
    Column("tradingsymbol", String(100), nullable=False),
    Column("name", String(255), nullable=True),
    Column("instrument_type", String(50), nullable=False),
    Column("tick_size", Numeric(12, 4), nullable=False),
    Column("lot_size", Integer, nullable=False, server_default="1"),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_tradingsymbol"),
)

candles = Table(
    "candles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("instrument_id", ForeignKey("instruments.id"), nullable=False),
    Column("timeframe", String(20), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("open_price", Numeric(18, 6), nullable=False),
    Column("high_price", Numeric(18, 6), nullable=False),
    Column("low_price", Numeric(18, 6), nullable=False),
    Column("close_price", Numeric(18, 6), nullable=False),
    Column("volume", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("instrument_id", "timeframe", "started_at", name="uq_candles_identity"),
)

signals = Table(
    "signals",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("instrument_id", ForeignKey("instruments.id"), nullable=False),
    Column("strategy_name", String(100), nullable=False),
    Column("signal_time", DateTime(timezone=True), nullable=False),
    Column("direction", String(20), nullable=False),
    Column("features", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

recommendations = Table(
    "recommendations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("signal_id", ForeignKey("signals.id"), nullable=False),
    Column("model_run_id", Integer, nullable=True),
    Column("verdict", String(50), nullable=False),
    Column("rationale", Text, nullable=True),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

risk_checks = Table(
    "risk_checks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("recommendation_id", ForeignKey("recommendations.id"), nullable=True),
    Column("result", String(50), nullable=False),
    Column("reason", Text, nullable=True),
    Column("checks", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("risk_check_id", ForeignKey("risk_checks.id"), nullable=True),
    Column("broker_order_id", String(100), nullable=True, unique=True),
    Column("instrument_id", ForeignKey("instruments.id"), nullable=True),
    Column("side", String(10), nullable=False),
    Column("order_type", String(50), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("limit_price", Numeric(18, 6), nullable=True),
    Column("status", String(50), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("quantity > 0", name="quantity_positive"),
)

order_events = Table(
    "order_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", ForeignKey("orders.id"), nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("broker_status", String(100), nullable=True),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

trades = Table(
    "trades",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entry_order_id", ForeignKey("orders.id"), nullable=True),
    Column("exit_order_id", ForeignKey("orders.id"), nullable=True),
    Column("instrument_id", ForeignKey("instruments.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("entry_price", Numeric(18, 6), nullable=True),
    Column("exit_price", Numeric(18, 6), nullable=True),
    Column("realized_pnl", Numeric(18, 6), nullable=True),
    Column("opened_at", DateTime(timezone=True), nullable=True),
    Column("closed_at", DateTime(timezone=True), nullable=True),
    Column("status", String(50), nullable=False),
    CheckConstraint("quantity > 0", name="quantity_positive"),
)

journal_entries = Table(
    "journal_entries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entry_type", String(100), nullable=False),
    Column("subject_type", String(100), nullable=True),
    Column("subject_id", Integer, nullable=True),
    Column("message", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

model_runs = Table(
    "model_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("provider", String(100), nullable=False),
    Column("model_name", String(100), nullable=False),
    Column("request_id", String(100), nullable=True),
    Column("input_payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("output_payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", String(50), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("ix_candles_instrument_timeframe_started", candles.c.instrument_id, candles.c.timeframe, candles.c.started_at)
Index("ix_signals_instrument_signal_time", signals.c.instrument_id, signals.c.signal_time)
Index("ix_journal_entries_created_at", journal_entries.c.created_at)
Index("ix_broker_sessions_broker_created_at", broker_sessions.c.broker, broker_sessions.c.created_at)
