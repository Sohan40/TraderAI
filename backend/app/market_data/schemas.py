"""Small market-data value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

KITE_WEBSOCKET_SOURCE = "KITE_WEBSOCKET"
SUPPORTED_STREAM_MODES = {"ltp", "quote", "full"}


@dataclass(frozen=True)
class WatchlistSymbol:
    """Configured watchlist symbol."""

    exchange: str
    tradingsymbol: str

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.tradingsymbol}"


@dataclass(frozen=True)
class InstrumentRecord:
    """Resolved local instrument."""

    id: int
    exchange: str
    tradingsymbol: str
    instrument_token: int
    tick_size: Decimal
    is_active: bool = True

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.tradingsymbol}"


@dataclass(frozen=True)
class InstrumentSyncResult:
    """Non-sensitive instrument sync counts."""

    fetched: int
    inserted: int
    updated: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class NormalizedTick:
    """Normalized quote tick used by candle aggregation."""

    instrument_token: int
    last_price: Decimal
    volume: int | None
    exchange_timestamp: datetime


@dataclass(frozen=True)
class CompletedCandle:
    """Completed one-minute candle ready for storage."""

    instrument_id: int
    timeframe: str
    started_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    source: str = KITE_WEBSOCKET_SOURCE


@dataclass(frozen=True)
class StreamStatus:
    """Non-sensitive stream lifecycle status."""

    enabled: bool
    websocket_enabled: bool
    running: bool
    connected: bool
    mode: str
    configured_symbols: int
    subscribed_symbols: int
    started_at: datetime | None
    last_tick_at: datetime | None
    last_activity_at: datetime | None
    stale: bool
    completed_candles: int
    last_error: str | None
