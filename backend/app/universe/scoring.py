"""Transparent deterministic scoring over completed local candles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analysis.feature_builder import build_feature_input, build_indicator_snapshot
from app.analysis.indicators import IST, NSE_OPEN, candle_continuity_ok
from app.analysis.schemas import CompletedBar
from app.core.config import Settings
from app.universe.schemas import UniverseSymbolResult

SCORE_WEIGHTS = {
    "liquidity_score": 15.0,
    "volatility_score": 15.0,
    "relative_volume_score": 15.0,
    "trend_score": 20.0,
    "breakout_readiness_score": 20.0,
    "data_quality_score": 15.0,
}


def score_symbol(
    *,
    symbol: str,
    bars: list[CompletedBar],
    benchmark_bars: list[CompletedBar],
    settings: Settings,
    timeframe: str,
    min_candles: int,
    use_current_session: bool,
    now: datetime,
    active_instrument: bool = True,
    stale_policy: str = "exclude",
) -> UniverseSymbolResult:
    warnings: list[str] = []
    exclusions: list[str] = []
    if timeframe != "1minute":
        exclusions.append("unsupported_timeframe")
    feature_input = build_feature_input(bars)
    current = feature_input.current_session_bars
    scoring_bars = current if use_current_session else feature_input.trailing_bars
    if len(scoring_bars) < min_candles:
        exclusions.append("insufficient_candles")
    session_start = bool(current) and current[0].started_at.astimezone(IST).time() == NSE_OPEN
    if use_current_session and not session_start:
        exclusions.append("session_start_missing")
    continuity = candle_continuity_ok(current, timeframe=timeframe)
    if settings.universe_selection_require_continuity and not continuity:
        exclusions.append("candle_continuity_failed")
    latest = bars[-1] if bars else None
    normalized_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    stale = bool(
        latest
        and normalized_now.astimezone(timezone.utc)
        > latest.started_at.astimezone(timezone.utc)
        + timedelta(minutes=2, seconds=settings.scanner_stale_after_seconds)
    )
    if stale and stale_policy == "exclude":
        exclusions.append("stale_data")
    elif stale and stale_policy == "warn":
        warnings.append("stale_data")
    if latest is None:
        return _excluded(symbol, exclusions or ["insufficient_candles"], warnings)

    indicators = build_indicator_snapshot(
        bars,
        benchmark_bars=benchmark_bars or None,
        opening_range_minutes=settings.scanner_opening_range_minutes,
    )
    latest_close = latest.close_price
    atr_pct = _pct(indicators.atr_14, latest_close)
    avg_volume = _average([Decimal(bar.volume) for bar in scoring_bars])
    avg_turnover = _average(
        [bar.close_price * Decimal(bar.volume) for bar in scoring_bars]
    )
    today_volume = Decimal(sum(bar.volume for bar in current))
    today_turnover = sum(
        (bar.close_price * Decimal(bar.volume) for bar in current),
        Decimal("0"),
    )
    historical_sessions = _session_totals(feature_input.prior_session_bars)
    historical_avg_volume = _average(list(historical_sessions.values()))
    relative_volume = (
        today_volume / historical_avg_volume
        if historical_avg_volume is not None and historical_avg_volume > 0
        else None
    )
    if relative_volume is None:
        warnings.append("relative_volume_unavailable")
    if not benchmark_bars:
        warnings.append("benchmark_missing")
    open_price = current[0].open_price if current else None
    previous_close = (
        feature_input.prior_session_bars[-1].close_price
        if feature_input.prior_session_bars
        else None
    )
    return_from_open = _pct_difference(latest_close, open_price)
    return_from_previous = _pct_difference(latest_close, previous_close)
    distance_vwap = _pct_difference(latest_close, indicators.vwap)
    ema9_vs_ema20 = _pct_difference(indicators.ema_9, indicators.ema_20)
    ema20_slope = _ema20_slope(bars)
    high_low_range = _pct(
        max(bar.high_price for bar in scoring_bars)
        - min(bar.low_price for bar in scoring_bars),
        latest_close,
    ) if scoring_bars else None
    opening_range_pct = (
        _pct(indicators.opening_range_high - indicators.opening_range_low, latest_close)
        if indicators.opening_range_high is not None
        and indicators.opening_range_low is not None
        else None
    )

    if latest_close < Decimal(str(settings.universe_selection_min_price)):
        exclusions.append("price_below_min")
    if latest_close > Decimal(str(settings.universe_selection_max_price)):
        exclusions.append("price_above_max")
    if (
        avg_turnover is not None
        and avg_turnover < Decimal(str(settings.universe_selection_min_avg_turnover))
    ):
        exclusions.append("avg_turnover_below_min")
    if atr_pct is None:
        warnings.append("atr_pct_unavailable")
    elif atr_pct < Decimal(str(settings.universe_selection_min_atr_pct)):
        exclusions.append("atr_pct_below_min")
    elif atr_pct > Decimal(str(settings.universe_selection_max_atr_pct)):
        exclusions.append("atr_pct_above_max")

    above_vwap = indicators.vwap is not None and latest_close > indicators.vwap
    above_previous_high = (
        indicators.previous_day_high is not None
        and latest_close > indicators.previous_day_high
    )
    trend_alignment = (
        indicators.ema_9 is not None
        and indicators.ema_20 is not None
        and latest_close > indicators.ema_9 > indicators.ema_20
    )
    near_opening_high = (
        indicators.opening_range_high is not None
        and latest_close >= indicators.opening_range_high * Decimal("0.995")
    )
    volume_expansion = relative_volume is not None and relative_volume >= Decimal("1.2")
    components = {
        "liquidity_score": _scaled(avg_turnover, Decimal("1000000"), 15.0),
        "volatility_score": _volatility_score(atr_pct),
        "relative_volume_score": _scaled(relative_volume, Decimal("2"), 15.0),
        "trend_score": round(
            sum(
                (
                    5.0 if above_vwap else 0.0,
                    5.0 if (ema9_vs_ema20 or Decimal("0")) > 0 else 0.0,
                    5.0 if (return_from_open or Decimal("0")) > 0 else 0.0,
                    5.0 if (ema20_slope or Decimal("0")) > 0 else 0.0,
                )
            ),
            4,
        ),
        "breakout_readiness_score": round(
            sum(
                (
                    5.0 if near_opening_high else 0.0,
                    5.0 if above_previous_high else 0.0,
                    5.0 if volume_expansion else 0.0,
                    5.0 if trend_alignment else 0.0,
                )
            ),
            4,
        ),
        "data_quality_score": 15.0 if not exclusions else 0.0,
    }
    metrics: dict[str, object] = {
        "has_instrument": True,
        "active_instrument": active_instrument,
        "candles_available": len(bars),
        "current_session_candles": len(current),
        "continuity_ok": continuity,
        "session_start_available": session_start,
        "last_candle_at": latest.started_at.isoformat(),
        "stale": stale,
        "latest_close": _number(latest_close),
        "avg_volume": _number(avg_volume),
        "avg_turnover": _number(avg_turnover),
        "today_volume": _number(today_volume),
        "today_turnover": _number(today_turnover),
        "relative_volume": _number(relative_volume),
        "atr14": _number(indicators.atr_14),
        "atr_pct": _number(atr_pct),
        "high_low_range_pct": _number(high_low_range),
        "opening_range_pct": _number(opening_range_pct),
        "return_from_open_pct": _number(return_from_open),
        "return_from_previous_close_pct": _number(return_from_previous),
        "distance_from_vwap_pct": _number(distance_vwap),
        "ema9_vs_ema20_pct": _number(ema9_vs_ema20),
        "ema20_slope_proxy": _number(ema20_slope),
        "relative_strength_vs_benchmark": _number(indicators.relative_index_move),
        "near_opening_range_high": near_opening_high,
        "above_vwap": above_vwap,
        "above_previous_day_high": above_previous_high,
        "volume_expansion": volume_expansion,
        "trend_alignment": trend_alignment,
    }
    return UniverseSymbolResult(
        symbol=symbol,
        rank=None,
        total_score=round(sum(components.values()), 4) if not exclusions else 0.0,
        component_scores=components,
        metrics=metrics,
        included=not exclusions,
        exclusion_reasons=list(dict.fromkeys(exclusions)),
        warnings=list(dict.fromkeys(warnings)),
    )


def _excluded(
    symbol: str,
    exclusions: list[str],
    warnings: list[str],
) -> UniverseSymbolResult:
    return UniverseSymbolResult(
        symbol=symbol,
        rank=None,
        total_score=0.0,
        component_scores={key: 0.0 for key in SCORE_WEIGHTS},
        metrics={},
        included=False,
        exclusion_reasons=list(dict.fromkeys(exclusions)),
        warnings=list(dict.fromkeys(warnings)),
    )


def _session_totals(bars: list[CompletedBar]) -> dict[object, Decimal]:
    totals: dict[object, Decimal] = {}
    for bar in bars:
        session = bar.started_at.astimezone(IST).date()
        totals[session] = totals.get(session, Decimal("0")) + Decimal(bar.volume)
    return totals


def _average(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _pct(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * Decimal("100")


def _pct_difference(value: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    if value is None or baseline is None:
        return None
    return _pct(value - baseline, baseline)


def _ema20_slope(bars: list[CompletedBar]) -> Decimal | None:
    if len(bars) < 21:
        return None
    previous = build_indicator_snapshot(bars[:-1]).ema_20
    current = build_indicator_snapshot(bars).ema_20
    return _pct_difference(current, previous)


def _scaled(value: Decimal | None, full_scale: Decimal, maximum: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return round(min(float(value / full_scale) * maximum, maximum), 4)


def _volatility_score(atr_pct: Decimal | None) -> float:
    if atr_pct is None:
        return 0.0
    distance = abs(float(atr_pct) - 1.5)
    return round(max(0.0, 15.0 - distance * 5.0), 4)


def _number(value: Decimal | None) -> float | None:
    return None if value is None else round(float(value), 6)
