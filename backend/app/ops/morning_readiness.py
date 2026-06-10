"""Aggregate local morning operational readiness without external calls."""

from __future__ import annotations

from typing import cast

from app.core.config import Settings
from app.market_data.stream_readiness import StreamReadinessService
from app.market_data.watchlist_validation import WatchlistValidationService
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.service import ScannerService


class MorningReadinessService:
    """Build a safe operator checklist from local configuration and state."""

    def __init__(
        self,
        *,
        settings: Settings,
        watchlist_service: WatchlistValidationService,
        stream_readiness_service: StreamReadinessService,
        scanner_service: ScannerService,
        auto_loop_service: ScannerAutoLoopService,
    ) -> None:
        self._settings = settings
        self._watchlist_service = watchlist_service
        self._stream_readiness_service = stream_readiness_service
        self._scanner_service = scanner_service
        self._auto_loop_service = auto_loop_service

    async def readiness(self) -> dict[str, object]:
        watchlist = await self._watchlist_service.validate()
        stream = await self._stream_readiness_service.readiness()
        scanner = await self._scanner_service.status()
        auto_loop = self._auto_loop_service.status()
        kite_session_ready = cast(bool, stream["kite_session_ready"])
        stream_running = cast(bool, stream["stream_already_running"])
        stream_connected = cast(bool, stream["stream_connected"])
        stream_warnings = cast(list[str], stream["warnings"])
        blocking: list[str] = []
        warnings: list[str] = []

        safe = self._settings.trading_mode == "OFF" and not self._settings.live_armed
        if not safe:
            blocking.append("trading_safety_defaults_not_off")
        if not watchlist.ready_for_stream:
            blocking.extend(watchlist.errors)
        if not kite_session_ready:
            blocking.append("kite_session_not_ready")
        if not self._settings.market_data_enabled:
            blocking.append("market_data_disabled")
        if not self._settings.kite_websocket_enabled:
            blocking.append("kite_websocket_disabled")
        if not stream_running:
            blocking.append("market_stream_not_running")
        elif not stream_connected:
            blocking.append("market_stream_not_connected")
        if self._settings.paper_enabled or self._settings.paper_mode != "OFF":
            warnings.append("paper_mode_should_remain_off_during_market_readiness")
        if not self._settings.scanner_enabled:
            warnings.append("scanner_disabled")
        if not self._settings.scanner_auto_loop_enabled:
            warnings.append("scanner_auto_loop_disabled")

        blocking = _unique(blocking)
        warnings = _unique(warnings + watchlist.warnings + stream_warnings)
        return {
            "safe": safe,
            "ready_for_market_open": safe and not blocking,
            "trading_mode": self._settings.trading_mode,
            "live_armed": self._settings.live_armed,
            "paper_enabled": self._settings.paper_enabled,
            "paper_mode": self._settings.paper_mode,
            "kite_session_status": stream["kite_session_status"],
            "market_data_enabled": self._settings.market_data_enabled,
            "websocket_enabled": self._settings.kite_websocket_enabled,
            "watchlist_validation": watchlist.as_dict(),
            "stream_readiness": stream,
            "scanner_status": scanner,
            "scanner_auto_loop_status": auto_loop,
            "blocking_issues": blocking,
            "warnings": warnings,
            "recommended_sequence": _recommended_sequence(
                watchlist_ready=watchlist.ready_for_stream,
                missing=watchlist.missing_symbols,
                session_ready=kite_session_ready,
                stream_running=stream_running,
                stream_connected=stream_connected,
            ),
        }


def _recommended_sequence(
    *,
    watchlist_ready: bool,
    missing: list[str],
    session_ready: bool,
    stream_running: bool,
    stream_connected: bool,
) -> list[str]:
    sequence = ["confirm_safe_env", "validate_watchlist"]
    if not session_ready:
        sequence.append("login_kite")
    if missing or not watchlist_ready:
        sequence.append("run_instrument_sync")
        sequence.append("validate_watchlist_again")
    sequence.append("force_recreate_api_after_env_change")
    if not stream_running or not stream_connected:
        sequence.append("start_market_stream")
    sequence.extend(
        [
            "confirm_subscribed_symbols_match_configured_symbols",
            "wait_until_10_07_before_scanning",
        ]
    )
    return _unique(sequence)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
