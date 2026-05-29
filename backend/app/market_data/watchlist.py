"""Configured watchlist parsing for the P04 MVP."""

from __future__ import annotations

from app.market_data.exceptions import WatchlistError
from app.market_data.schemas import WatchlistSymbol

MVP_EXCHANGE = "NSE"


def parse_watchlist(raw_watchlist: str, max_instruments: int) -> list[WatchlistSymbol]:
    """Parse EXCHANGE:TRADINGSYMBOL entries and enforce MVP limits."""
    if max_instruments < 1:
        raise WatchlistError("Market data max instruments must be at least 1.")

    entries = [entry.strip() for entry in raw_watchlist.split(",") if entry.strip()]
    if not entries:
        raise WatchlistError("Market data watchlist is empty.")
    if len(entries) > max_instruments:
        raise WatchlistError("Market data watchlist exceeds configured maximum.")

    seen: set[str] = set()
    symbols: list[WatchlistSymbol] = []
    for entry in entries:
        if ":" not in entry:
            raise WatchlistError("Watchlist entries must use EXCHANGE:TRADINGSYMBOL.")
        exchange, tradingsymbol = (part.strip().upper() for part in entry.split(":", 1))
        if not exchange or not tradingsymbol:
            raise WatchlistError("Watchlist entries must include exchange and trading symbol.")
        if exchange != MVP_EXCHANGE:
            raise WatchlistError("P04 market data is restricted to NSE instruments.")
        key = f"{exchange}:{tradingsymbol}"
        if key in seen:
            raise WatchlistError("Duplicate watchlist symbol configured.")
        seen.add(key)
        symbols.append(WatchlistSymbol(exchange=exchange, tradingsymbol=tradingsymbol))

    return symbols
