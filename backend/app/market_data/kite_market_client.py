"""Read-only Kite market-data client boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from app.market_data.exceptions import MarketDataStreamError
from app.market_data.schemas import SUPPORTED_STREAM_MODES

TickCallback = Callable[[list[Mapping[str, Any]]], None]


class KiteQuoteStream(Protocol):
    """Minimal quote-stream surface used by P04."""

    on_ticks: Any
    on_connect: Any
    on_close: Any
    on_error: Any

    def connect(self, threaded: bool = True) -> None:
        """Connect to the quote stream."""

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        """Subscribe to read-only quote tokens."""

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        """Set read-only quote mode."""

    def close(self) -> None:
        """Close the quote stream."""


class KiteMarketClient(Protocol):
    """Read-only Kite market-data operations only."""

    def fetch_instruments(self, *, api_key: str, access_token: str) -> list[Mapping[str, Any]]:
        """Fetch the daily instrument master dump."""

    def create_quote_stream(
        self,
        *,
        api_key: str,
        access_token: str,
        on_ticks: TickCallback,
        on_connect: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> KiteQuoteStream:
        """Create a read-only quote WebSocket client."""

    def subscribe(self, stream: KiteQuoteStream, instrument_tokens: Sequence[int]) -> None:
        """Subscribe to configured instrument tokens."""

    def set_mode(self, stream: KiteQuoteStream, mode: str, instrument_tokens: Sequence[int]) -> None:
        """Set the stream mode to ltp, quote, or full."""

    def disconnect(self, stream: KiteQuoteStream) -> None:
        """Disconnect the quote stream."""


class KiteConnectMarketClient:
    """Official Kite-backed market client with no execution methods."""

    def fetch_instruments(self, *, api_key: str, access_token: str) -> list[Mapping[str, Any]]:
        from kiteconnect import KiteConnect  # type: ignore[import-untyped]

        client = KiteConnect(api_key=api_key)
        client.set_access_token(access_token)
        return list(client.instruments(exchange="NSE"))

    def create_quote_stream(
        self,
        *,
        api_key: str,
        access_token: str,
        on_ticks: TickCallback,
        on_connect: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> KiteQuoteStream:
        from kiteconnect import KiteTicker

        ticker = KiteTicker(api_key, access_token)
        ticker.on_ticks = lambda _ws, ticks: on_ticks(list(ticks))
        ticker.on_connect = lambda _ws, _response: on_connect() if on_connect else None
        ticker.on_close = lambda _ws, _code, _reason: on_close() if on_close else None
        ticker.on_error = lambda _ws, _code, _reason: on_error("kite_websocket_error") if on_error else None
        return ticker

    def subscribe(self, stream: KiteQuoteStream, instrument_tokens: Sequence[int]) -> None:
        stream.subscribe(list(instrument_tokens))

    def set_mode(self, stream: KiteQuoteStream, mode: str, instrument_tokens: Sequence[int]) -> None:
        if mode not in SUPPORTED_STREAM_MODES:
            raise MarketDataStreamError("Unsupported Kite WebSocket mode.")
        stream.set_mode(mode, list(instrument_tokens))

    def disconnect(self, stream: KiteQuoteStream) -> None:
        stream.close()
