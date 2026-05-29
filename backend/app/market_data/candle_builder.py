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
    volume_complete: bool

    def update_price(self, price: Decimal) -> None:
        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        self.close_price = price

    def add_volume_delta(self, delta: int) -> None:
        self.volume += delta

    def mark_incomplete(self) -> None:
        self.volume_complete = False

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
    """Aggregate completed UTC candles and ignore duplicate/out-of-order ticks.

    Kite quote ticks expose cumulative session volume. Candle volume is built
    by adding positive cross-tick cumulative-volume deltas to the minute bucket
    of the current tick. The first observed tick after startup is a baseline
    only, so that initial partial minute is deliberately not persisted.
    """

    def __init__(self, timeframe: str = "1minute") -> None:
        self._timeframe = timeframe
        self._working: dict[int, _WorkingCandle] = {}
        self._last_tick_at: dict[int, datetime] = {}
        self._last_cumulative_volume: dict[int, int] = {}

    def accept_tick(self, tick: NormalizedTick, instrument_id: int) -> list[CompletedCandle]:
        """Accept a tick and return any newly completed candles."""
        tick_time = _as_utc(tick.exchange_timestamp)
        last_tick_at = self._last_tick_at.get(tick.instrument_token)
        previous_volume = self._last_cumulative_volume.get(tick.instrument_token)

        if last_tick_at is not None and tick_time < last_tick_at:
            return []
        if (
            last_tick_at is not None
            and tick_time == last_tick_at
            and not _has_positive_volume_delta(previous_volume, tick.volume)
        ):
            return []

        minute = tick_time.replace(second=0, microsecond=0)
        completed = self._roll_to_minute(tick.instrument_token, minute)
        current = self._working.get(tick.instrument_token)

        if current is None:
            current = _new_working_candle(
                instrument_id=instrument_id,
                timeframe=self._timeframe,
                started_at=minute,
                tick=tick,
                volume_complete=previous_volume is not None,
            )
            self._working[tick.instrument_token] = current
        else:
            current.update_price(tick.last_price)

        self._last_tick_at[tick.instrument_token] = tick_time

        if tick.volume is None:
            return completed

        if previous_volume is None:
            self._last_cumulative_volume[tick.instrument_token] = tick.volume
            current.mark_incomplete()
            return completed

        if tick.volume < previous_volume:
            self._last_cumulative_volume[tick.instrument_token] = tick.volume
            current.mark_incomplete()
            return completed

        current.add_volume_delta(tick.volume - previous_volume)
        self._last_cumulative_volume[tick.instrument_token] = tick.volume
        return completed

    def flush_completed_before(self, cutoff: datetime) -> list[CompletedCandle]:
        """Flush candles whose minute is complete before the provided UTC cutoff."""
        cutoff_minute = _as_utc(cutoff).replace(second=0, microsecond=0)
        completed: list[CompletedCandle] = []
        for token, candle in list(self._working.items()):
            if candle.started_at < cutoff_minute and candle.volume_complete:
                completed.append(candle.complete())
                del self._working[token]
        return completed

    def _roll_to_minute(self, instrument_token: int, minute: datetime) -> list[CompletedCandle]:
        current = self._working.get(instrument_token)
        if current is None or current.started_at == minute:
            return []

        completed = [current.complete()] if current.volume_complete else []
        del self._working[instrument_token]
        return completed


def _new_working_candle(
    *,
    instrument_id: int,
    timeframe: str,
    started_at: datetime,
    tick: NormalizedTick,
    volume_complete: bool,
) -> _WorkingCandle:
    return _WorkingCandle(
        instrument_id=instrument_id,
        timeframe=timeframe,
        started_at=started_at,
        open_price=tick.last_price,
        high_price=tick.last_price,
        low_price=tick.last_price,
        close_price=tick.last_price,
        volume=0,
        volume_complete=volume_complete,
    )


def _has_positive_volume_delta(previous_volume: int | None, current_volume: int | None) -> bool:
    return previous_volume is not None and current_volume is not None and current_volume > previous_volume


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
