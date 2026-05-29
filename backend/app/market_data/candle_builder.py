"""One-minute candle aggregation from normalized quote ticks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.market_data.schemas import CompletedCandle, NormalizedTick


@dataclass
class _WorkingCandle:
    instrument_id: int
    timeframe: str
    started_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int

    def update(self, price: Decimal, volume: int | None) -> None:
        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        self.close_price = price
        if volume is not None:
            self.volume = max(self.volume, volume)

    def complete(self) -> CompletedCandle:
        return CompletedCandle(
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            started_at=self.started_at,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume,
        )


class OneMinuteCandleBuilder:
    """Aggregate only completed candles and ignore duplicate/out-of-order ticks."""

    def __init__(self, timeframe: str = "1minute") -> None:
        self._timeframe = timeframe
        self._working: dict[int, _WorkingCandle] = {}
        self._last_tick_at: dict[int, datetime] = {}

    def accept_tick(self, tick: NormalizedTick, instrument_id: int) -> list[CompletedCandle]:
        """Accept a tick and return any newly completed candles."""
        tick_time = _as_utc(tick.exchange_timestamp)
        last_tick_at = self._last_tick_at.get(tick.instrument_token)
        if last_tick_at is not None and tick_time <= last_tick_at:
            return []
        self._last_tick_at[tick.instrument_token] = tick_time

        minute = tick_time.replace(second=0, microsecond=0)
        current = self._working.get(tick.instrument_token)
        if current is None:
            self._working[tick.instrument_token] = _new_working_candle(
                instrument_id=instrument_id,
                timeframe=self._timeframe,
                started_at=minute,
                tick=tick,
            )
            return []

        if minute == current.started_at:
            current.update(tick.last_price, tick.volume)
            return []

        completed = [current.complete()]
        self._working[tick.instrument_token] = _new_working_candle(
            instrument_id=instrument_id,
            timeframe=self._timeframe,
            started_at=minute,
            tick=tick,
        )
        return completed

    def flush_completed_before(self, cutoff: datetime) -> list[CompletedCandle]:
        """Flush candles whose minute is complete before the provided UTC cutoff."""
        cutoff_minute = _as_utc(cutoff).replace(second=0, microsecond=0)
        completed: list[CompletedCandle] = []
        for token, candle in list(self._working.items()):
            if candle.started_at < cutoff_minute:
                completed.append(candle.complete())
                del self._working[token]
        return completed


def _new_working_candle(
    *,
    instrument_id: int,
    timeframe: str,
    started_at: datetime,
    tick: NormalizedTick,
) -> _WorkingCandle:
    volume = tick.volume if tick.volume is not None else 0
    return _WorkingCandle(
        instrument_id=instrument_id,
        timeframe=timeframe,
        started_at=started_at,
        open_price=tick.last_price,
        high_price=tick.last_price,
        low_price=tick.last_price,
        close_price=tick.last_price,
        volume=volume,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
