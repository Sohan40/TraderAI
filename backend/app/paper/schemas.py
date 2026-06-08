"""Typed P06 paper-trading value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

PAPER_TIMEFRAME = "1minute"
PAPER_ENTRY_ORDER_TYPE = "LIMIT"
PAPER_EXIT_ORDER_TYPE = "PAPER_EXIT"
PAPER_ENTRY_SUBMITTED = "PAPER_ENTRY_SUBMITTED"
PAPER_ENTRY_FILLED = "PAPER_ENTRY_FILLED"
PAPER_ENTRY_NO_FILL = "PAPER_ENTRY_NO_FILL"
PAPER_EXIT_FILLED = "PAPER_EXIT_FILLED"
PAPER_TRADE_CLOSED = "PAPER_CLOSED"
PAPER_TRADE_DATA_ENDED = "PAPER_DATA_ENDED"
PAPER_ENTRY_ATTEMPT_ENTRY_TYPE = "PAPER_ENTRY_ATTEMPT"
PAPER_REJECTION_ENTRY_TYPE = "PAPER_REJECTION"
PAPER_TRADE_ENTRY_TYPE = "PAPER_TRADE"


class PaperMode(str, Enum):
    """Safe P06 modes; LIVE is present only to reject explicitly."""

    OFF = "OFF"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    LIVE = "LIVE"


class PaperExitReason(str, Enum):
    """Deterministic paper lifecycle outcomes."""

    NO_FILL = "NO_FILL"
    STOP_HIT = "STOP_HIT"
    TARGET_HIT = "TARGET_HIT"
    TIME_EXIT = "TIME_EXIT"
    FORCE_FLAT = "FORCE_FLAT"
    DATA_ENDED = "DATA_ENDED"
    INVALID_SIGNAL_CONTEXT = "INVALID_SIGNAL_CONTEXT"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    MODE_DISABLED = "MODE_DISABLED"
    LIVE_NOT_IMPLEMENTED = "LIVE_NOT_IMPLEMENTED"


@dataclass(frozen=True)
class PaperConfig:
    """Paper engine settings copied from safe runtime config."""

    enabled: bool
    mode: PaperMode
    max_trades_per_day: int
    default_quantity: int
    entry_buffer_pct: Decimal
    stop_pct: Decimal
    target_r_multiple: Decimal
    force_flat_time_ist: time
    estimated_cost_per_trade: Decimal


@dataclass(frozen=True)
class PaperSignal:
    """Persisted P05 signal shape consumed by P06."""

    id: int
    instrument_id: int
    signal_key: str
    symbol: str
    strategy_name: str
    strategy_version: str
    signal_status: str
    signal_time: datetime
    direction: str
    veto_reasons: list[str]
    features: dict[str, Any]
    replay_run_id: str | None = None


@dataclass(frozen=True)
class PaperInstruction:
    """Deterministic simulated order instruction."""

    signal_id: int
    signal_key: str
    symbol: str
    strategy_name: str
    signal_time: datetime
    entry_reference_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    quantity: int
    paper_max_risk: Decimal
    paper_mode: PaperMode
    estimated_costs: Decimal
    simulated: bool = True

    def as_payload(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id,
            "signal_key": self.signal_key,
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "signal_time": _iso(self.signal_time),
            "entry_reference_price": _money(self.entry_reference_price),
            "stop_price": _money(self.stop_price),
            "target_price": _money(self.target_price),
            "quantity": self.quantity,
            "paper_max_risk": _money(self.paper_max_risk),
            "paper_mode": self.paper_mode.value,
            "estimated_costs": _money(self.estimated_costs),
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class PaperSimulationResult:
    """Full paper outcome persisted to journal/reporting."""

    signal_id: int
    signal_key: str
    symbol: str
    strategy_name: str
    paper_mode: PaperMode
    simulated: bool
    entry_order_status: str
    entry_reference_price: Decimal | None
    entry_fill_status: str
    entry_fill_time: datetime | None
    entry_fill_price: Decimal | None
    quantity: int
    stop_price: Decimal | None
    target_price: Decimal | None
    exit_time: datetime | None
    exit_price: Decimal | None
    exit_reason: PaperExitReason
    gross_pnl: Decimal
    estimated_costs: Decimal
    net_estimated_pnl: Decimal
    rejection_reason: str | None = None
    trade_created: bool = False

    def as_payload(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id,
            "signal_key": self.signal_key,
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "simulated": self.simulated,
            "paper_mode": self.paper_mode.value,
            "entry_order_status": self.entry_order_status,
            "entry_reference_price": _maybe_money(self.entry_reference_price),
            "entry_fill_status": self.entry_fill_status,
            "entry_fill_time": _maybe_iso(self.entry_fill_time),
            "entry_fill_price": _maybe_money(self.entry_fill_price),
            "quantity": self.quantity,
            "stop_price": _maybe_money(self.stop_price),
            "target_price": _maybe_money(self.target_price),
            "exit_time": _maybe_iso(self.exit_time),
            "exit_price": _maybe_money(self.exit_price),
            "exit_reason": self.exit_reason.value,
            "gross_pnl": _money(self.gross_pnl),
            "estimated_costs": _money(self.estimated_costs),
            "net_estimated_pnl": _money(self.net_estimated_pnl),
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True)
class PaperReplaySummary:
    """Bounded summary returned by service, route and CLI."""

    paper_enabled: bool
    paper_mode: PaperMode
    signals_loaded: int
    outcomes: list[PaperSimulationResult]

    @property
    def entry_attempts(self) -> int:
        return sum(
            1
            for outcome in self.outcomes
            if outcome.entry_order_status in {PAPER_ENTRY_FILLED, PAPER_ENTRY_NO_FILL}
        )

    @property
    def no_fill_outcomes(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.exit_reason == PaperExitReason.NO_FILL)

    @property
    def trades_created(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.trade_created)

    @property
    def rejections(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.rejection_reason)

    @property
    def gross_pnl(self) -> Decimal:
        return sum((outcome.gross_pnl for outcome in self.outcomes), Decimal("0"))

    @property
    def estimated_costs(self) -> Decimal:
        return sum((outcome.estimated_costs for outcome in self.outcomes), Decimal("0"))

    @property
    def net_estimated_pnl(self) -> Decimal:
        return sum((outcome.net_estimated_pnl for outcome in self.outcomes), Decimal("0"))

    def as_dict(self) -> dict[str, object]:
        return {
            "paper_enabled": self.paper_enabled,
            "paper_mode": self.paper_mode.value,
            "signals_loaded": self.signals_loaded,
            "candidate_signals_loaded": self.signals_loaded,
            "entry_attempts": self.entry_attempts,
            "no_fill_outcomes": self.no_fill_outcomes,
            "trades_created": self.trades_created,
            "filled_paper_trades": self.trades_created,
            "rejections": self.rejections,
            "gross_pnl": _money(self.gross_pnl),
            "estimated_costs": _money(self.estimated_costs),
            "net_estimated_pnl": _money(self.net_estimated_pnl),
            "outcomes": [outcome.as_payload() for outcome in self.outcomes],
        }


def rejected_outcome(
    *,
    signal: PaperSignal,
    config: PaperConfig,
    exit_reason: PaperExitReason,
    rejection_reason: str,
) -> PaperSimulationResult:
    """Build a non-trading paper rejection outcome."""
    return PaperSimulationResult(
        signal_id=signal.id,
        signal_key=signal.signal_key,
        symbol=signal.symbol,
        strategy_name=signal.strategy_name,
        paper_mode=config.mode,
        simulated=True,
        entry_order_status="NOT_CREATED",
        entry_reference_price=None,
        entry_fill_status="NOT_FILLED",
        entry_fill_time=None,
        entry_fill_price=None,
        quantity=0,
        stop_price=None,
        target_price=None,
        exit_time=None,
        exit_price=None,
        exit_reason=exit_reason,
        gross_pnl=Decimal("0"),
        estimated_costs=Decimal("0"),
        net_estimated_pnl=Decimal("0"),
        rejection_reason=rejection_reason,
        trade_created=False,
    )


def no_fill_outcome(
    *,
    instruction: PaperInstruction,
) -> PaperSimulationResult:
    """Build a deterministic limit no-fill result."""
    return PaperSimulationResult(
        signal_id=instruction.signal_id,
        signal_key=instruction.signal_key,
        symbol=instruction.symbol,
        strategy_name=instruction.strategy_name,
        paper_mode=instruction.paper_mode,
        simulated=True,
        entry_order_status=PAPER_ENTRY_NO_FILL,
        entry_reference_price=instruction.entry_reference_price,
        entry_fill_status="NO_FILL",
        entry_fill_time=None,
        entry_fill_price=None,
        quantity=instruction.quantity,
        stop_price=instruction.stop_price,
        target_price=instruction.target_price,
        exit_time=None,
        exit_price=None,
        exit_reason=PaperExitReason.NO_FILL,
        gross_pnl=Decimal("0"),
        estimated_costs=Decimal("0"),
        net_estimated_pnl=Decimal("0"),
        trade_created=False,
    )


def completed_trade_outcome(
    *,
    instruction: PaperInstruction,
    entry_fill_time: datetime,
    exit_time: datetime | None,
    exit_price: Decimal | None,
    exit_reason: PaperExitReason,
) -> PaperSimulationResult:
    """Build a filled paper trade outcome."""
    costs = instruction.estimated_costs if exit_price is not None else Decimal("0")
    gross = Decimal("0")
    if exit_price is not None:
        gross = (exit_price - instruction.entry_reference_price) * Decimal(instruction.quantity)
    return PaperSimulationResult(
        signal_id=instruction.signal_id,
        signal_key=instruction.signal_key,
        symbol=instruction.symbol,
        strategy_name=instruction.strategy_name,
        paper_mode=instruction.paper_mode,
        simulated=True,
        entry_order_status=PAPER_ENTRY_FILLED,
        entry_reference_price=instruction.entry_reference_price,
        entry_fill_status="FILLED",
        entry_fill_time=entry_fill_time,
        entry_fill_price=instruction.entry_reference_price,
        quantity=instruction.quantity,
        stop_price=instruction.stop_price,
        target_price=instruction.target_price,
        exit_time=exit_time,
        exit_price=exit_price,
        exit_reason=exit_reason,
        gross_pnl=gross,
        estimated_costs=costs,
        net_estimated_pnl=gross - costs,
        trade_created=True,
    )


def _iso(value: datetime) -> str:
    return value.isoformat()


def _maybe_iso(value: datetime | None) -> str | None:
    return None if value is None else _iso(value)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))


def _maybe_money(value: Decimal | None) -> str | None:
    return None if value is None else _money(value)
