"""Exactly two deterministic long-only P05 scanner strategies."""

from __future__ import annotations

from decimal import Decimal

from app.analysis.feature_builder import build_feature_snapshot
from app.analysis.schemas import CompletedBar, QuoteContext
from app.scanners.schemas import CANDIDATE, REJECTED_SIGNAL, ScannerConfig, ScannerEvaluation
from app.scanners.vetoes import INVALID_INDICATOR_STATE, hard_vetoes


def evaluate_strategy(
    *,
    strategy_name: str,
    instrument_id: int,
    symbol: str,
    timeframe: str,
    bars: list[CompletedBar],
    config: ScannerConfig,
    benchmark_bars: list[CompletedBar] | None = None,
    quote_context: QuoteContext | None = None,
    replay_run_id: str | None = None,
) -> ScannerEvaluation:
    """Evaluate one configured long-only strategy."""
    if strategy_name == "opening_range_breakout_long":
        return _opening_range_breakout_long(
            instrument_id=instrument_id,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            config=config,
            benchmark_bars=benchmark_bars,
            quote_context=quote_context,
            replay_run_id=replay_run_id,
        )
    if strategy_name == "vwap_pullback_continuation_long":
        return _vwap_pullback_continuation_long(
            instrument_id=instrument_id,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            config=config,
            benchmark_bars=benchmark_bars,
            quote_context=quote_context,
            replay_run_id=replay_run_id,
        )
    raise ValueError("unsupported strategy")


def _opening_range_breakout_long(
    *,
    instrument_id: int,
    symbol: str,
    timeframe: str,
    bars: list[CompletedBar],
    config: ScannerConfig,
    benchmark_bars: list[CompletedBar] | None,
    quote_context: QuoteContext | None,
    replay_run_id: str | None,
) -> ScannerEvaluation:
    strategy_name = "opening_range_breakout_long"
    snapshot = build_feature_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        strategy_name=strategy_name,
        signal_status=REJECTED_SIGNAL,
        veto_reasons=[],
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        opening_range_minutes=config.opening_range_minutes,
    )
    vetoes = hard_vetoes(
        symbol=symbol,
        bars=bars,
        indicators=snapshot.indicator_values,
        data_quality=snapshot.data_quality,
        config=config,
        strategy_name=strategy_name,
    )
    latest = bars[-1]
    indicators = snapshot.indicator_values
    condition = (
        indicators.opening_range_high is not None
        and latest.close_price > indicators.opening_range_high
        and indicators.ema_9 is not None
        and indicators.ema_20 is not None
        and indicators.ema_9 > indicators.ema_20
        and indicators.vwap is not None
        and latest.close_price > indicators.vwap
        and indicators.volume_ratio is not None
        and indicators.volume_ratio >= Decimal(str(config.min_volume_ratio))
    )
    if not condition:
        vetoes.append(INVALID_INDICATOR_STATE)
    return _evaluation(
        instrument_id=instrument_id,
        symbol=symbol,
        strategy_name=strategy_name,
        timeframe=timeframe,
        bars=bars,
        config=config,
        vetoes=vetoes,
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        replay_run_id=replay_run_id,
    )


def _vwap_pullback_continuation_long(
    *,
    instrument_id: int,
    symbol: str,
    timeframe: str,
    bars: list[CompletedBar],
    config: ScannerConfig,
    benchmark_bars: list[CompletedBar] | None,
    quote_context: QuoteContext | None,
    replay_run_id: str | None,
) -> ScannerEvaluation:
    strategy_name = "vwap_pullback_continuation_long"
    snapshot = build_feature_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        strategy_name=strategy_name,
        signal_status=REJECTED_SIGNAL,
        veto_reasons=[],
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        opening_range_minutes=config.opening_range_minutes,
    )
    vetoes = hard_vetoes(
        symbol=symbol,
        bars=bars,
        indicators=snapshot.indicator_values,
        data_quality=snapshot.data_quality,
        config=config,
        strategy_name=strategy_name,
    )
    latest = bars[-1]
    previous = bars[-2] if len(bars) >= 2 else None
    indicators = snapshot.indicator_values
    condition = (
        previous is not None
        and indicators.vwap is not None
        and indicators.ema_9 is not None
        and indicators.ema_20 is not None
        and indicators.ema_9 >= indicators.ema_20
        and previous.close_price <= indicators.vwap
        and latest.close_price > indicators.vwap
        and latest.close_price > previous.high_price
        and indicators.volume_ratio is not None
        and indicators.volume_ratio >= Decimal(str(config.min_volume_ratio))
    )
    if not condition:
        vetoes.append(INVALID_INDICATOR_STATE)
    return _evaluation(
        instrument_id=instrument_id,
        symbol=symbol,
        strategy_name=strategy_name,
        timeframe=timeframe,
        bars=bars,
        config=config,
        vetoes=vetoes,
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        replay_run_id=replay_run_id,
    )


def _evaluation(
    *,
    instrument_id: int,
    symbol: str,
    strategy_name: str,
    timeframe: str,
    bars: list[CompletedBar],
    config: ScannerConfig,
    vetoes: list[str],
    benchmark_bars: list[CompletedBar] | None,
    quote_context: QuoteContext | None,
    replay_run_id: str | None,
) -> ScannerEvaluation:
    status = REJECTED_SIGNAL if vetoes else CANDIDATE
    snapshot = build_feature_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        strategy_name=strategy_name,
        signal_status=status,
        veto_reasons=_unique(vetoes),
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        opening_range_minutes=config.opening_range_minutes,
    )
    signal_key_parts = [
        replay_run_id or "live",
        symbol,
        timeframe,
        strategy_name,
        snapshot.strategy_version,
        bars[-1].started_at.isoformat(),
    ]
    return ScannerEvaluation(
        instrument_id=instrument_id,
        symbol=symbol,
        strategy_name=strategy_name,
        signal_key=":".join(signal_key_parts),
        status=status,
        signal_time=bars[-1].started_at,
        veto_reasons=snapshot.veto_reasons,
        snapshot=snapshot,
        replay_run_id=replay_run_id,
    )


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
