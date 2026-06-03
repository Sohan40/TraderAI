"""Build immutable feature snapshots from completed candles only."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.indicators import (
    atr_wilder,
    candle_continuity_ok,
    ema,
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
    closes = [bar.close_price for bar in bars]
    opening_high, opening_low = opening_range(bars, range_minutes=opening_range_minutes)
    previous_high, previous_low = previous_day_high_low(bars)
    return IndicatorSnapshot(
        ema_9=ema(closes, 9),
        ema_20=ema(closes, 20),
        ema_50=ema(closes, 50),
        rsi_14=rsi_wilder(closes, 14),
        atr_14=atr_wilder(bars, 14),
        vwap=vwap(bars),
        opening_range_high=opening_high,
        opening_range_low=opening_low,
        previous_day_high=previous_high,
        previous_day_low=previous_low,
        volume_ratio=volume_ratio(bars, 20),
        relative_index_move=relative_index_movement(bars, benchmark_bars),
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
) -> FeatureSnapshot:
    """Build a deterministic scanner evidence snapshot."""
    if not bars:
        bar_closed_at = datetime.now(timezone.utc)
    else:
        bar_closed_at = bars[-1].started_at
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
        candle_continuity_ok=candle_continuity_ok(bars, timeframe=timeframe),
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
    )
