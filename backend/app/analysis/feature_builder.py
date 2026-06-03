"""Build immutable feature snapshots from completed candles only."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.analysis.indicators import (
    atr_wilder,
    candle_continuity_ok,
    ema,
    IST,
    NSE_OPEN,
    opening_range,
    previous_day_high_low,
    relative_index_movement,
    rsi_wilder,
    spread_pct,
    volume_ratio,
    vwap,
)
from app.analysis.schemas import (
    CompletedBar,
    DataQuality,
    FeatureSnapshot,
    FeatureInput,
    IndicatorSnapshot,
    QuoteContext,
)

STRATEGY_VERSION = "p05_v1"


def build_indicator_snapshot(
    bars: list[CompletedBar],
    *,
    benchmark_bars: list[CompletedBar] | None = None,
    quote_context: QuoteContext | None = None,
    opening_range_minutes: int = 15,
) -> IndicatorSnapshot:
    """Build indicator values with unavailable values represented as None."""
    feature_input = build_feature_input(bars)
    closes = [bar.close_price for bar in feature_input.trailing_bars]
    opening_high, opening_low = opening_range(
        feature_input.current_session_bars,
        range_minutes=opening_range_minutes,
    )
    previous_high, previous_low = previous_day_high_low(
        feature_input.prior_session_bars + feature_input.current_session_bars
    )
    benchmark_input = build_feature_input(benchmark_bars or [])
    return IndicatorSnapshot(
        ema_9=ema(closes, 9),
        ema_20=ema(closes, 20),
        ema_50=ema(closes, 50),
        rsi_14=rsi_wilder(closes, 14),
        atr_14=atr_wilder(feature_input.trailing_bars, 14),
        vwap=vwap(feature_input.current_session_bars),
        opening_range_high=opening_high,
        opening_range_low=opening_low,
        previous_day_high=previous_high,
        previous_day_low=previous_low,
        volume_ratio=volume_ratio(feature_input.trailing_bars, 20),
        relative_index_move=relative_index_movement(
            feature_input.trailing_bars,
            benchmark_input.trailing_bars,
        ),
        spread_pct=spread_pct(quote_context),
    )


def build_feature_snapshot(
    *,
    symbol: str,
    timeframe: str,
    bars: list[CompletedBar],
    strategy_name: str,
    signal_status: str,
    veto_reasons: list[str],
    benchmark_bars: list[CompletedBar] | None = None,
    quote_context: QuoteContext | None = None,
    opening_range_minutes: int = 15,
    future_live_qualification: dict[str, object] | None = None,
) -> FeatureSnapshot:
    """Build a deterministic scanner evidence snapshot."""
    if not bars:
        bar_closed_at = datetime.now(timezone.utc)
    else:
        bar_closed_at = bars[-1].started_at
    feature_input = build_feature_input(bars)
    indicators = build_indicator_snapshot(
        bars,
        benchmark_bars=benchmark_bars,
        quote_context=quote_context,
        opening_range_minutes=opening_range_minutes,
    )
    data_quality = DataQuality(
        history_complete=all(
            value is not None
            for value in (
                indicators.ema_9,
                indicators.ema_20,
                indicators.ema_50,
                indicators.rsi_14,
                indicators.atr_14,
                indicators.vwap,
                indicators.volume_ratio,
            )
        ),
        quote_fresh=quote_context is not None,
        spread_available=indicators.spread_pct is not None,
        candle_continuity_ok=candle_continuity_ok(
            feature_input.current_session_bars,
            timeframe=timeframe,
        ),
    )
    return FeatureSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        bar_closed_at=bar_closed_at,
        strategy_name=strategy_name,
        strategy_version=STRATEGY_VERSION,
        indicator_values=indicators,
        data_quality=data_quality,
        signal_status=signal_status,
        veto_reasons=veto_reasons,
        future_live_qualification=future_live_qualification or {},
    )


def build_feature_input(bars: list[CompletedBar]) -> FeatureInput:
    """Split loaded candles into deterministic scanner feature scopes."""
    ordered = sorted(bars, key=lambda bar: bar.started_at)
    regular_bars = [bar for bar in ordered if _is_regular_session_bar(bar)]
    if not ordered:
        return FeatureInput(
            all_bars=[],
            trailing_bars=[],
            current_session_bars=[],
            prior_session_bars=[],
        )
    current_session_date = _session_date(ordered[-1])
    prior_dates = sorted(
        {_session_date(bar) for bar in regular_bars if _session_date(bar) < current_session_date}
    )
    prior_session_date = prior_dates[-1] if prior_dates else None
    return FeatureInput(
        all_bars=ordered,
        trailing_bars=regular_bars,
        current_session_bars=[
            bar for bar in regular_bars if _session_date(bar) == current_session_date
        ],
        prior_session_bars=[
            bar
            for bar in regular_bars
            if prior_session_date is not None and _session_date(bar) == prior_session_date
        ],
    )


def _session_date(bar: CompletedBar) -> date:
    return bar.started_at.astimezone(IST).date()


def _is_regular_session_bar(bar: CompletedBar) -> bool:
    return bar.started_at.astimezone(IST).time() >= NSE_OPEN
