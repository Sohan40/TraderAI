"""Typed data for deterministic indicator and scanner features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CompletedBar:
    """Completed OHLCV candle used by P05."""

    instrument_id: int
    symbol: str
    timeframe: str
    started_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int


@dataclass(frozen=True)
class QuoteContext:
    """Optional quote context; unavailable when not backed by stored quote/depth data."""

    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    quote_time: datetime | None = None


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Deterministic feature values for a strategy/bar evaluation."""

    ema_9: Decimal | None
    ema_20: Decimal | None
    ema_50: Decimal | None
    rsi_14: Decimal | None
    atr_14: Decimal | None
    vwap: Decimal | None
    opening_range_high: Decimal | None
    opening_range_low: Decimal | None
    previous_day_high: Decimal | None
    previous_day_low: Decimal | None
    volume_ratio: Decimal | None
    relative_index_move: Decimal | None
    spread_pct: Decimal | None

    def as_dict(self) -> dict[str, str | None]:
        return {key: _decimal_to_str(value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class DataQuality:
    """Non-sensitive data-quality facts used by vetoes."""

    history_complete: bool
    quote_fresh: bool
    spread_available: bool
    candle_continuity_ok: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "history_complete": self.history_complete,
            "quote_fresh": self.quote_fresh,
            "spread_available": self.spread_available,
            "candle_continuity_ok": self.candle_continuity_ok,
        }


@dataclass(frozen=True)
class FeatureSnapshot:
    """Immutable scanner evidence generated from completed candles only."""

    symbol: str
    timeframe: str
    bar_closed_at: datetime
    strategy_name: str
    strategy_version: str
    indicator_values: IndicatorSnapshot
    data_quality: DataQuality
    signal_status: str
    veto_reasons: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_closed_at": self.bar_closed_at.isoformat(),
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "indicator_values": self.indicator_values.as_dict(),
            "data_quality": self.data_quality.as_dict(),
            "signal_status": self.signal_status,
            "veto_reasons": list(self.veto_reasons),
        }


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
