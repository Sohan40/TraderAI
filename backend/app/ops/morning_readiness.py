"""Aggregate local morning operational readiness without external calls."""

from __future__ import annotations

from typing import cast

from app.core.config import Settings
from app.market_data.stream_readiness import StreamReadinessService
from app.market_data.watchlist_validation import WatchlistValidationService
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.service import ScannerService
from app.universe.service import UniverseSelectionService


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
        universe_service: UniverseSelectionService | None = None,
    ) -> None:
        self._settings = settings
        self._watchlist_service = watchlist_service
        self._stream_readiness_service = stream_readiness_service
        self._scanner_service = scanner_service
        self._auto_loop_service = auto_loop_service
        self._universe_service = universe_service

    async def readiness(self) -> dict[str, object]:
        watchlist = await self._watchlist_service.validate()
        stream = await self._stream_readiness_service.readiness()
        scanner = await self._scanner_service.status()
        auto_loop = await self._auto_loop_service.status()
        universe = (
            await self._universe_service.status()
            if self._universe_service is not None
            else {
                "enabled": False,
                "latest_run_at": None,
                "latest_selected_count": 0,
                "latest_selected_symbols": [],
                "pool_valid": True,
            }
        )
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
        universe_enabled = bool(universe["enabled"])
        universe_pool_valid = bool(universe["pool_valid"])
        latest_universe_exists = bool(universe["latest_run_at"])
        if universe_enabled and not universe_pool_valid:
            warnings.append("universe_pool_invalid")
        if universe_enabled and not latest_universe_exists:
            warnings.append("universe_selection_has_no_latest_run")
        if (
            self._settings.scanner_auto_loop_use_selected_universe
            and not latest_universe_exists
        ):
            blocking.append("scanner_auto_loop_selected_universe_missing")

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
            "universe_selection_enabled": universe_enabled,
            "universe_pool_valid": universe_pool_valid,
            "latest_universe_run_at": universe["latest_run_at"],
            "latest_selected_count": universe["latest_selected_count"],
            "latest_selected_symbols": universe["latest_selected_symbols"],
            "blocking_issues": blocking,
            "warnings": warnings,
            "recommended_sequence": _recommended_sequence(
                watchlist_ready=watchlist.ready_for_stream,
                missing=watchlist.missing_symbols,
                session_ready=kite_session_ready,
                stream_running=stream_running,
                stream_connected=stream_connected,
                universe_enabled=universe_enabled,
                latest_universe_exists=latest_universe_exists,
            ),
        }


def _recommended_sequence(
    *,
    watchlist_ready: bool,
    missing: list[str],
    session_ready: bool,
    stream_running: bool,
    stream_connected: bool,
    universe_enabled: bool,
    latest_universe_exists: bool,
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
    if universe_enabled and not latest_universe_exists:
        sequence.append("run_universe_selection_after_data_available")
        sequence.append("use_market_watchlist_until_universe_selection_exists")
    sequence.extend(
        [
            "confirm_subscribed_symbols_match_configured_symbols",
            "wait_until_10_07_before_scanning",
        ]
    )
    return _unique(sequence)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
