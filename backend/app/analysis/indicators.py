"""Pure deterministic indicator calculations over completed candles."""

from __future__ import annotations

from datetime import time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.analysis.schemas import CompletedBar, QuoteContext

IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
NSE_OPEN = time(9, 15)
ONE_HUNDRED = Decimal("100")
FOUR_PLACES = Decimal("0.0001")


def ema(values: list[Decimal], period: int) -> Decimal | None:
    """Return EMA seeded with the SMA of the first period values."""
    if period < 1 or len(values) < period:
        return None
    seed = sum(values[:period]) / Decimal(period)
    multiplier = Decimal(2) / Decimal(period + 1)
    current = seed
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return _q(current)


def rsi_wilder(closes: list[Decimal], period: int = 14) -> Decimal | None:
    """Return Wilder RSI; requires period + 1 completed closes."""
    if len(closes) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(closes[:period], closes[1: period + 1], strict=True):
        change = current - previous
        gains.append(max(change, Decimal("0")))
        losses.append(max(-change, Decimal("0")))
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    for previous, current in zip(closes[period:-1], closes[period + 1:], strict=True):
        change = current - previous
        gain = max(change, Decimal("0"))
        loss = max(-change, Decimal("0"))
        avg_gain = ((avg_gain * Decimal(period - 1)) + gain) / Decimal(period)
        avg_loss = ((avg_loss * Decimal(period - 1)) + loss) / Decimal(period)
    if avg_loss == 0:
        return ONE_HUNDRED
    rs = avg_gain / avg_loss
    return _q(ONE_HUNDRED - (ONE_HUNDRED / (Decimal(1) + rs)))


def atr_wilder(bars: list[CompletedBar], period: int = 14) -> Decimal | None:
    """Return Wilder ATR; requires period + 1 completed bars."""
    if len(bars) < period + 1:
        return None
    true_ranges: list[Decimal] = []
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        true_ranges.append(
            max(
                current.high_price - current.low_price,
                abs(current.high_price - previous.close_price),
                abs(current.low_price - previous.close_price),
            )
        )
    current_atr = sum(true_ranges[:period]) / Decimal(period)
    for true_range in true_ranges[period:]:
        current_atr = ((current_atr * Decimal(period - 1)) + true_range) / Decimal(period)
    return _q(current_atr)


def vwap(bars: list[CompletedBar]) -> Decimal | None:
    """Return VWAP using typical price (high + low + close) / 3 weighted by volume."""
    total_volume = sum(bar.volume for bar in bars)
    if not bars or total_volume <= 0:
        return None
    weighted = sum(_typical_price(bar) * Decimal(bar.volume) for bar in bars)
    return _q(weighted / Decimal(total_volume))


def opening_range(
    bars: list[CompletedBar],
    *,
    range_minutes: int = 15,
) -> tuple[Decimal | None, Decimal | None]:
    """Return high/low for bars starting in the configured IST opening range."""
    if not bars:
        return None, None
    current_date = bars[-1].started_at.astimezone(IST).date()
    selected = [
        bar
        for bar in bars
        if bar.started_at.astimezone(IST).date() == current_date
        and _minutes_since_open(bar) is not None
        and 0 <= (_minutes_since_open(bar) or 0) < range_minutes
    ]
    if not selected:
        return None, None
    return max(bar.high_price for bar in selected), min(bar.low_price for bar in selected)


def previous_day_high_low(bars: list[CompletedBar]) -> tuple[Decimal | None, Decimal | None]:
    """Return prior IST session high/low when prior-session bars exist."""
    if not bars:
        return None, None
    current_date = bars[-1].started_at.astimezone(IST).date()
    prior = [bar for bar in bars if bar.started_at.astimezone(IST).date() < current_date]
    if not prior:
        return None, None
    latest_prior_date = max(bar.started_at.astimezone(IST).date() for bar in prior)
    selected = [bar for bar in prior if bar.started_at.astimezone(IST).date() == latest_prior_date]
    return max(bar.high_price for bar in selected), min(bar.low_price for bar in selected)


def volume_ratio(bars: list[CompletedBar], baseline_period: int = 20) -> Decimal | None:
    """Return current volume divided by average volume of previous baseline bars."""
    if len(bars) < baseline_period + 1:
        return None
    baseline = bars[-baseline_period - 1: -1]
    average = sum(Decimal(bar.volume) for bar in baseline) / Decimal(baseline_period)
    if average <= 0:
        return None
    return _q(Decimal(bars[-1].volume) / average)


def relative_index_movement(
    symbol_bars: list[CompletedBar],
    benchmark_bars: list[CompletedBar] | None,
) -> Decimal | None:
    """Return latest symbol percent move minus benchmark percent move."""
    if benchmark_bars is None or len(symbol_bars) < 2 or len(benchmark_bars) < 2:
        return None
    symbol_move = _pct_move(symbol_bars[-2].close_price, symbol_bars[-1].close_price)
    benchmark_move = _pct_move(benchmark_bars[-2].close_price, benchmark_bars[-1].close_price)
    if symbol_move is None or benchmark_move is None:
        return None
    return _q(symbol_move - benchmark_move)


def spread_pct(context: QuoteContext | None) -> Decimal | None:
    """Return bid/ask spread percent only when actual quote context is supplied."""
    if context is None or context.bid_price is None or context.ask_price is None:
        return None
    mid = (context.bid_price + context.ask_price) / Decimal(2)
    if mid <= 0 or context.ask_price < context.bid_price:
        return None
    return _q(((context.ask_price - context.bid_price) / mid) * ONE_HUNDRED)


def candle_continuity_ok(bars: list[CompletedBar], *, timeframe: str) -> bool:
    """Check deterministic continuity for adjacent one-minute bars."""
    if timeframe != "1minute" or len(bars) < 2:
        return True
    deltas = [
        int((current.started_at - previous.started_at).total_seconds())
        for previous, current in zip(bars[:-1], bars[1:], strict=True)
    ]
    return all(delta == 60 for delta in deltas)


def _typical_price(bar: CompletedBar) -> Decimal:
    return (bar.high_price + bar.low_price + bar.close_price) / Decimal(3)


def _pct_move(previous: Decimal, current: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * ONE_HUNDRED


def _minutes_since_open(bar: CompletedBar) -> int | None:
    local = bar.started_at.astimezone(IST)
    open_minutes = NSE_OPEN.hour * 60 + NSE_OPEN.minute
    bar_minutes = local.hour * 60 + local.minute
    return bar_minutes - open_minutes


def _q(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)
