"""Deterministic preliminary scanner vetoes."""

from __future__ import annotations

from datetime import time, timedelta, timezone
from decimal import Decimal

from app.analysis.schemas import CompletedBar, DataQuality, IndicatorSnapshot
from app.scanners.schemas import ScannerConfig

IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
ENTRY_END = time(14, 30)

UNSUPPORTED_SYMBOL = "unsupported_symbol"
MISSING_HISTORY = "missing_history"
STALE_QUOTE_OR_DATA = "stale_quote_or_data"
SPREAD_TOO_WIDE = "spread_too_wide"
SPREAD_UNAVAILABLE_WHEN_REQUIRED = "spread_unavailable_when_required"
OUTSIDE_CONFIGURED_TIME_WINDOW = "outside_configured_time_window"
DATA_QUALITY_FAILURE = "data_quality_failure"
BENCHMARK_DATA_MISSING_WHEN_REQUIRED = "benchmark_data_missing_when_required"
INVALID_INDICATOR_STATE = "invalid_indicator_state"
DUPLICATE_SIGNAL = "duplicate_signal"


def hard_vetoes(
    *,
    symbol: str,
    bars: list[CompletedBar],
    indicators: IndicatorSnapshot,
    data_quality: DataQuality,
    config: ScannerConfig,
    strategy_name: str,
    is_stale: bool = False,
) -> list[str]:
    """Return deterministic hard veto reasons for normal missing-data cases."""
    reasons: list[str] = []
    if not symbol.startswith("NSE:"):
        reasons.append(UNSUPPORTED_SYMBOL)
    if not data_quality.history_complete:
        reasons.append(MISSING_HISTORY)
    if not data_quality.candle_continuity_ok:
        reasons.append(DATA_QUALITY_FAILURE)
    if is_stale:
        reasons.append(STALE_QUOTE_OR_DATA)
    if bars and bars[-1].started_at.astimezone(IST).time() > ENTRY_END:
        reasons.append(OUTSIDE_CONFIGURED_TIME_WINDOW)
    if config.benchmark_symbol and indicators.relative_index_move is None:
        reasons.append(BENCHMARK_DATA_MISSING_WHEN_REQUIRED)
    spread_required = (
        strategy_name == config.future_live_eligible_strategy
        and config.require_spread_for_future_live
    )
    spread_required_now = spread_required and config.observation_mode.upper() != "SHADOW"
    if spread_required_now:
        if indicators.spread_pct is None:
            reasons.append(SPREAD_UNAVAILABLE_WHEN_REQUIRED)
        elif indicators.spread_pct > Decimal(str(config.max_spread_pct)):
            reasons.append(SPREAD_TOO_WIDE)
    if indicators.spread_pct is not None and indicators.spread_pct > Decimal(str(config.max_spread_pct)):
        reasons.append(SPREAD_TOO_WIDE)
    return _unique(reasons)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
