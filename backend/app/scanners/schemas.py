"""Scanner value objects and constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.analysis.schemas import FeatureSnapshot

CANDIDATE = "CANDIDATE"
REJECTED_SIGNAL = "REJECTED_SIGNAL"
LONG = "LONG"
SCANNER_TIMEFRAME = "1minute"
P05_STRATEGIES = {"opening_range_breakout_long", "vwap_pullback_continuation_long"}


@dataclass(frozen=True)
class ScannerConfig:
    """Scanner configuration copied from safe settings."""

    enabled: bool
    strategies: list[str]
    observation_mode: str
    future_live_eligible_strategy: str
    opening_range_minutes: int
    stale_after_seconds: int
    min_volume_ratio: float
    max_spread_pct: float
    require_spread_for_future_live: bool
    benchmark_symbol: str | None


@dataclass(frozen=True)
class SignalRecord:
    """Persisted immutable scanner observation."""

    id: int
    signal_key: str
    symbol: str
    strategy_name: str
    strategy_version: str
    signal_status: str
    signal_time: datetime
    direction: str
    veto_reasons: list[str]
    features: dict[str, object]
    replay_run_id: str | None = None


@dataclass(frozen=True)
class ScannerEvaluation:
    """Strategy evaluation before persistence."""

    instrument_id: int
    symbol: str
    strategy_name: str
    signal_key: str
    status: str
    signal_time: datetime
    veto_reasons: list[str]
    snapshot: FeatureSnapshot
    replay_run_id: str | None = None


@dataclass(frozen=True)
class ScannerRunResult:
    """Non-sensitive scanner run counts."""

    evaluated: int
    inserted: int
    duplicates: int
    candidates: int
    rejected: int
    veto_counts: dict[str, int]
