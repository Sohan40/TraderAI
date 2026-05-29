"""Controlled read-only Kite quote stream service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.broker.session_provider import AccessSessionProvider
from app.core.config import Settings
from app.market_data.candle_builder import OneMinuteCandleBuilder
from app.market_data.exceptions import (
    MarketDataDisabledError,
    MarketDataSessionError,
    MarketDataStreamError,
    WatchlistError,
)
from app.market_data.kite_market_client import KiteMarketClient, KiteQuoteStream
from app.market_data.repository import MarketDataRepository
from app.market_data.schemas import InstrumentRecord, NormalizedTick, SUPPORTED_STREAM_MODES, StreamStatus
from app.market_data.watchlist import parse_watchlist

logger = logging.getLogger(__name__)


class MarketDataStreamService:
    """Start, stop and observe a disabled-by-default read-only quote stream."""

    def __init__(
        self,
        *,
        settings: Settings,
        market_client: KiteMarketClient,
        repository: MarketDataRepository,
        session_provider: AccessSessionProvider,
        candle_builder: OneMinuteCandleBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._market_client = market_client
        self._repository = repository
        self._session_provider = session_provider
        self._candle_builder = candle_builder or OneMinuteCandleBuilder(
            settings.market_data_candle_interval
        )
        self._stream: KiteQuoteStream | None = None
        self._started_at: datetime | None = None
        self._connected = False
        self._last_tick_at: datetime | None = None
        self._last_activity_at: datetime | None = None
        self._last_error: str | None = None
        self._completed_candles = 0
        self._resolved: list[InstrumentRecord] = []
        self._instrument_by_token: dict[int, InstrumentRecord] = {}
        self._pending_completed: list[Any] = []
        self._stale_logged = False

    async def start(self) -> dict[str, object]:
        """Start the quote stream only after all safety gates pass."""
        self._ensure_enabled()
        if self._stream is not None:
            return self.status_dict()

        watchlist = parse_watchlist(
            self._settings.market_data_watchlist,
            self._settings.market_data_max_instruments,
        )
        resolved = await self._repository.resolve_watchlist(watchlist)
        if len(resolved) != len(watchlist):
            raise WatchlistError("Configured watchlist symbols must be synced before streaming.")

        try:
            kite_session = await self._session_provider.get_active_session()
        except Exception as exc:
            raise MarketDataSessionError("Active Kite session is required for market streaming.") from exc

        self._resolved = resolved
        self._instrument_by_token = {item.instrument_token: item for item in resolved}
        tokens = list(self._instrument_by_token)
        now = datetime.now(timezone.utc)
        self._started_at = now
        self._last_activity_at = now
        self._last_error = None

        try:
            self._stream = self._market_client.create_quote_stream(
                api_key=kite_session.api_key,
                access_token=kite_session.access_token,
                on_ticks=self.handle_ticks,
                on_connect=self._mark_connected,
                on_close=self._mark_disconnected,
                on_error=self._mark_error,
            )
            self._stream.connect(threaded=True)
            self._market_client.subscribe(self._stream, tokens)
            self._market_client.set_mode(self._stream, self._settings.market_data_mode, tokens)
            self._connected = True
        except Exception as exc:
            self._stream = None
            self._connected = False
            self._last_error = "stream_start_failed"
            logger.warning("market data stream failed to start")
            raise MarketDataStreamError("Market data stream could not be started.") from exc

        logger.info("market data stream started symbol_count=%s", len(tokens))
        return self.status_dict()

    async def stop(self) -> dict[str, object]:
        """Stop the quote stream without flushing the in-progress candle."""
        if self._stream is not None:
            self._market_client.disconnect(self._stream)
        self._stream = None
        self._connected = False
        self._last_activity_at = datetime.now(timezone.utc)
        logger.info("market data stream stopped")
        return self.status_dict()

    def handle_ticks(self, ticks: list[Mapping[str, Any]]) -> None:
        """Normalize callback ticks and persist newly completed candles."""
        now = datetime.now(timezone.utc)
        self._last_activity_at = now
        completed = []
        for raw_tick in ticks:
            tick = normalize_tick(raw_tick)
            instrument = self._instrument_by_token.get(tick.instrument_token)
            if instrument is None:
                continue
            self._last_tick_at = tick.exchange_timestamp.astimezone(timezone.utc)
            completed.extend(self._candle_builder.accept_tick(tick, instrument.id))
        if completed:
            self._completed_candles += len(completed)
            logger.info("market data candles completed count=%s", len(completed))
            self._save_completed(completed)

    def status(self) -> StreamStatus:
        """Return non-sensitive stream status."""
        now = datetime.now(timezone.utc)
        stale_after = timedelta(seconds=self._settings.market_data_stale_after_seconds)
        stale = bool(self._last_activity_at and now - self._last_activity_at > stale_after)
        if stale and not self._stale_logged:
            logger.warning("market data stream stale")
            self._stale_logged = True
        if not stale:
            self._stale_logged = False
        configured_count = len(
            parse_watchlist(
                self._settings.market_data_watchlist,
                self._settings.market_data_max_instruments,
            )
        )
        return StreamStatus(
            enabled=self._settings.market_data_enabled,
            websocket_enabled=self._settings.kite_websocket_enabled,
            running=self._stream is not None,
            connected=self._connected,
            mode=self._settings.market_data_mode,
            configured_symbols=configured_count,
            subscribed_symbols=len(self._resolved),
            started_at=self._started_at,
            last_tick_at=self._last_tick_at,
            last_activity_at=self._last_activity_at,
            stale=stale,
            completed_candles=self._completed_candles,
            last_error=self._last_error,
        )

    def status_dict(self) -> dict[str, object]:
        """Return a JSON-safe, non-sensitive status response."""
        status = self.status()
        return {
            "enabled": status.enabled,
            "websocket_enabled": status.websocket_enabled,
            "running": status.running,
            "connected": status.connected,
            "mode": status.mode,
            "configured_symbols": status.configured_symbols,
            "subscribed_symbols": status.subscribed_symbols,
            "started_at": status.started_at.isoformat() if status.started_at else None,
            "last_tick_at": status.last_tick_at.isoformat() if status.last_tick_at else None,
            "last_activity_at": status.last_activity_at.isoformat()
            if status.last_activity_at
            else None,
            "stale": status.stale,
            "completed_candles": status.completed_candles,
            "last_error": status.last_error,
        }

    def _ensure_enabled(self) -> None:
        if not self._settings.market_data_enabled:
            raise MarketDataDisabledError("Market data is disabled.")
        if not self._settings.kite_websocket_enabled:
            raise MarketDataDisabledError("Kite WebSocket is disabled.")
        if self._settings.market_data_mode not in SUPPORTED_STREAM_MODES:
            raise MarketDataStreamError("Unsupported market data mode.")

    def _mark_connected(self) -> None:
        self._connected = True
        self._last_activity_at = datetime.now(timezone.utc)

    def _mark_disconnected(self) -> None:
        self._connected = False
        self._last_activity_at = datetime.now(timezone.utc)

    def _mark_error(self, category: str) -> None:
        self._last_error = category
        self._last_activity_at = datetime.now(timezone.utc)
        logger.warning("market data stream error category=%s", category)

    def _save_completed(self, completed: list[Any]) -> None:
        """Persist completed candles from callbacks without exposing raw ticks."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._repository.save_completed_candles(completed))
        else:
            loop.create_task(self._repository.save_completed_candles(completed))

    async def flush_pending(self) -> int:
        """Persist completed candles accumulated by callback handling."""
        pending = getattr(self, "_pending_completed", [])
        if not pending:
            return 0
        self._pending_completed = []
        return await self._repository.save_completed_candles(pending)


def normalize_tick(raw_tick: Mapping[str, Any]) -> NormalizedTick:
    """Normalize Kite/fake quote ticks without retaining the raw payload."""
    token = int(raw_tick["instrument_token"])
    price = Decimal(str(raw_tick.get("last_price", raw_tick.get("last_traded_price"))))
    timestamp = raw_tick.get("exchange_timestamp") or raw_tick.get("timestamp")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    volume_raw = raw_tick.get("volume_traded") or raw_tick.get("volume")
    volume = int(volume_raw) if volume_raw is not None else None
    return NormalizedTick(
        instrument_token=token,
        last_price=price,
        volume=volume,
        exchange_timestamp=timestamp.astimezone(timezone.utc),
    )
