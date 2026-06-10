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


@dataclass(frozen=True)
class ScannerSymbolResult:
    """One symbol result inside a batch or auto-loop run."""

    symbol: str
    evaluated: int = 0
    inserted: int = 0
    duplicates: int = 0
    candidates: int = 0
    rejected: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "evaluated": self.evaluated,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "candidates": self.candidates,
            "rejected": self.rejected,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


@dataclass(frozen=True)
class ScannerBatchResult:
    """Non-sensitive scanner batch summary."""

    evaluated_symbols: int
    total_evaluated: int
    total_inserted: int
    total_duplicates: int
    total_candidates: int
    total_rejected: int
    per_symbol: list[ScannerSymbolResult]
    errors: dict[str, str]
    started_at: datetime
    finished_at: datetime

    def as_dict(self) -> dict[str, object]:
        duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        return {
            "evaluated_symbols": self.evaluated_symbols,
            "total_evaluated": self.total_evaluated,
            "total_inserted": self.total_inserted,
            "total_duplicates": self.total_duplicates,
            "total_candidates": self.total_candidates,
            "total_rejected": self.total_rejected,
            "per_symbol": [item.as_dict() for item in self.per_symbol],
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": duration_ms,
        }
