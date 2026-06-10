"""DB-only stream readiness diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.broker.session_store import BROKER_ZERODHA, STATUS_ACTIVE, SessionStore
from app.core.config import Settings
from app.market_data.schemas import SUPPORTED_STREAM_MODES
from app.market_data.watchlist_validation import WatchlistValidationService


class StreamStatusProvider(Protocol):
    """Non-sensitive process-local stream status boundary."""

    def status_dict(self) -> dict[str, object]:
        """Return stream state without side effects."""


class StreamReadinessService:
    """Explain whether the existing read-only stream can be started."""

    def __init__(
        self,
        *,
        settings: Settings,
        watchlist_service: WatchlistValidationService,
        session_store: SessionStore,
        stream_status_provider: StreamStatusProvider,
    ) -> None:
        self._settings = settings
        self._watchlist_service = watchlist_service
        self._session_store = session_store
        self._stream_status_provider = stream_status_provider

    async def readiness(self) -> dict[str, object]:
        watchlist = await self._watchlist_service.validate()
        session = await self._session_status()
        stream = self._stream_status_provider.status_dict()
        errors: list[str] = []
        warnings = list(watchlist.warnings)

        if not self._settings.market_data_enabled:
            errors.append("market_data_disabled")
        if not self._settings.kite_websocket_enabled:
            errors.append("kite_websocket_disabled")
        if self._settings.market_data_mode not in SUPPORTED_STREAM_MODES:
            errors.append("unsupported_market_data_mode")
        errors.extend(watchlist.errors)
        if not session["ready"]:
            errors.append("kite_session_not_ready")

        stream_running = bool(stream.get("running"))
        stream_connected = bool(stream.get("connected"))
        if stream_running and not stream_connected:
            warnings.append("stream_running_but_not_connected")
        gates_ready = not errors
        can_start = gates_ready and not stream_running
        ready = gates_ready and (can_start or stream_connected)
        action = _recommended_action(
            errors=errors,
            watchlist_errors=watchlist.errors,
            missing=watchlist.missing_symbols,
            inactive=watchlist.inactive_symbols,
            session_ready=bool(session["ready"]),
            stream_running=stream_running,
            stream_connected=stream_connected,
        )
        return {
            "ready": ready,
            "can_start_stream": can_start,
            "market_data_enabled": self._settings.market_data_enabled,
            "websocket_enabled": self._settings.kite_websocket_enabled,
            "mode": self._settings.market_data_mode,
            "watchlist_ready": watchlist.ready_for_stream,
            "kite_session_ready": session["ready"],
            "kite_session_status": session,
            "stream_already_running": stream_running,
            "stream_connected": stream_connected,
            "configured_symbols": watchlist.configured_count,
            "configured_symbol_values": watchlist.normalized_symbols,
            "resolved_symbols_count": len(watchlist.resolved_symbols),
            "subscribed_symbols": stream.get("subscribed_symbols", 0),
            "missing_symbols": watchlist.missing_symbols,
            "inactive_symbols": watchlist.inactive_symbols,
            "last_error": stream.get("last_error"),
            "api_env_loaded": True,
            "api_env_snapshot": {
                "watchlist_source": watchlist.source,
                "raw_watchlist": watchlist.raw_watchlist,
                "max_instruments": watchlist.max_instruments,
            },
            "errors": _unique(errors),
            "warnings": _unique(warnings),
            "recommended_next_action": action,
        }

    async def _session_status(self) -> dict[str, object]:
        configured = bool(
            self._settings.kite_auth_enabled
            and self._settings.kite_api_key
            and self._settings.kite_session_encryption_key
        )
        if not configured:
            return {
                "ready": False,
                "configured": configured,
                "status": None,
                "expired": False,
            }
        record = await self._session_store.get_latest_session(BROKER_ZERODHA)
        if record is None:
            return {
                "ready": False,
                "configured": True,
                "status": None,
                "expired": False,
            }
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expired = expires_at <= datetime.now(timezone.utc)
        ready = (
            record.status == STATUS_ACTIVE
            and record.invalidated_at is None
            and not expired
        )
        return {
            "ready": ready,
            "configured": True,
            "status": record.status,
            "expired": expired,
            "expires_at": expires_at.isoformat(),
        }


def _recommended_action(
    *,
    errors: list[str],
    watchlist_errors: list[str],
    missing: list[str],
    inactive: list[str],
    session_ready: bool,
    stream_running: bool,
    stream_connected: bool,
) -> str:
    if "watchlist_entries_must_use_exchange_colon_tradingsymbol" in watchlist_errors:
        return "fix_watchlist_format"
    if "duplicate_watchlist_symbol" in watchlist_errors:
        return "remove_duplicate_watchlist_symbols"
    if "only_nse_supported_in_current_mvp" in watchlist_errors:
        return "use_nse_symbols_only"
    if "watchlist_exceeds_configured_maximum" in watchlist_errors:
        return "increase_market_data_max_instruments"
    if missing or inactive:
        return "run_instrument_sync"
    if not session_ready:
        return "login_kite"
    if "market_data_disabled" in errors or "kite_websocket_disabled" in errors:
        return "enable_read_only_market_data"
    if "unsupported_market_data_mode" in errors:
        return "fix_market_data_mode"
    if stream_running and not stream_connected:
        return "inspect_stream_error_before_restart"
    if stream_running:
        return "stream_already_running"
    return "ready_to_start_stream"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
