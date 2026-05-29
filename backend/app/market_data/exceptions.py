"""Market-data specific safe failure types."""


class MarketDataError(Exception):
    """Base market-data error."""


class MarketDataDisabledError(MarketDataError):
    """Raised when market data is disabled by configuration."""


class InstrumentSyncDisabledError(MarketDataDisabledError):
    """Raised when instrument sync is disabled."""


class WatchlistError(MarketDataError):
    """Raised for invalid watchlist configuration."""


class MarketDataSessionError(MarketDataError):
    """Raised when an active Kite session is unavailable."""


class MarketDataStreamError(MarketDataError):
    """Raised when stream startup or operation fails safely."""
