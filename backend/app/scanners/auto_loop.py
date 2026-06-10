"""Disabled-by-default in-process scanner scheduling over stored candles."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone

from app.analysis.indicators import IST
from app.core.config import Settings
from app.market_data.watchlist_validation import configured_watchlist_entries
from app.scanners.exceptions import (
    ScannerAutoLoopBusyError,
    ScannerAutoLoopDisabledError,
    ScannerAutoLoopRunningError,
    ScannerConfigError,
    ScannerDisabledError,
)
from app.scanners.service import ScannerService
from app.universe.exceptions import SelectedUniverseMissingError


class ScannerAutoLoopService:
    """Operator-started scheduler for deterministic scanner batches."""

    def __init__(
        self,
        *,
        settings: Settings,
        scanner_service: ScannerService,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._scanner_service = scanner_service
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._task: asyncio.Task[None] | None = None
        self._run_lock = asyncio.Lock()
        self._last_run_at: datetime | None = None
        self._next_run_after: datetime | None = None
        self._last_summary: dict[str, object] | None = None
        self._last_error: str | None = None

    async def start(self) -> dict[str, object]:
        """Start the loop only when scanner and auto-loop flags are enabled."""
        self._ensure_enabled()
        if self._task is not None and not self._task.done():
            raise ScannerAutoLoopRunningError("Scanner auto-loop is already running.")
        self._task = asyncio.create_task(self._loop(), name="scanner-auto-loop")
        return self.status()

    async def stop(self) -> dict[str, object]:
        """Stop the loop idempotently without affecting market streaming."""
        task = self._task
        self._task = None
        self._next_run_after = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self.status()

    async def run_now(self) -> dict[str, object]:
        """Run one controlled auto-loop batch using configured policy."""
        self._ensure_enabled()
        if self._run_lock.locked():
            raise ScannerAutoLoopBusyError("Scanner auto-loop run is already in progress.")
        async with self._run_lock:
            now = self._normalized_now()
            skip_reason = self._time_skip_reason(now)
            if skip_reason is not None:
                summary = {
                    "skipped": True,
                    "skip_reason": skip_reason,
                    "evaluated_symbols": 0,
                    "total_evaluated": 0,
                    "total_inserted": 0,
                    "total_candidates": 0,
                    "total_rejected": 0,
                    "per_symbol": [],
                    "errors": {},
                    "started_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "duration_ms": 0,
                }
                self._last_run_at = now
                self._last_summary = summary
                self._last_error = None
                return summary
            try:
                batch = await self._scanner_service.run_batch(
                    symbols=self._configured_symbols_or_none(),
                    timeframe=self._settings.scanner_auto_loop_timeframe,
                    store_rejections=self._settings.scanner_auto_loop_store_rejections,
                    dry_run=False,
                    max_symbols=self._settings.scanner_auto_loop_max_symbols,
                    min_candles=self._settings.scanner_auto_loop_min_candles,
                    require_session_start=self._settings.scanner_auto_loop_require_session_start,
                    require_continuity=self._settings.scanner_auto_loop_require_continuity,
                    use_latest_universe=(
                        self._settings.scanner_auto_loop_use_selected_universe
                    ),
                )
                summary = batch.as_dict()
                summary["skipped"] = False
                self._last_summary = summary
                self._last_error = None
                self._last_run_at = self._normalized_now()
                return summary
            except SelectedUniverseMissingError:
                summary = {
                    "skipped": True,
                    "skip_reason": "selected_universe_missing",
                    "evaluated_symbols": 0,
                    "total_evaluated": 0,
                    "total_inserted": 0,
                    "total_candidates": 0,
                    "total_rejected": 0,
                    "per_symbol": [],
                    "errors": {},
                    "started_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "duration_ms": 0,
                }
                self._last_summary = summary
                self._last_error = "selected_universe_missing"
                self._last_run_at = now
                return summary
            except Exception:
                self._last_error = "scanner_auto_loop_run_failed"
                raise

    def status(self) -> dict[str, object]:
        """Return non-sensitive loop state."""
        return {
            "enabled": self._settings.scanner_auto_loop_enabled,
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self._settings.scanner_auto_loop_interval_seconds,
            "symbols": self._status_symbols(),
            "timeframe": self._settings.scanner_auto_loop_timeframe,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "next_run_after": (
                self._next_run_after.isoformat() if self._next_run_after else None
            ),
            "last_summary": self._last_summary,
            "last_error": self._last_error,
            "store_rejections": self._settings.scanner_auto_loop_store_rejections,
            "overlap_prevention": True,
            "min_candles": self._settings.scanner_auto_loop_min_candles,
            "start_after_ist": self._settings.scanner_auto_loop_start_after_ist,
            "stop_after_ist": self._settings.scanner_auto_loop_stop_after_ist,
            "suppress_duplicate_rejections": (
                self._settings.scanner_auto_loop_suppress_duplicate_rejections
            ),
            "candidates_always_persist": (
                self._settings.scanner_auto_loop_candidates_always_persist
            ),
            "use_selected_universe": (
                self._settings.scanner_auto_loop_use_selected_universe
            ),
        }

    async def _loop(self) -> None:
        try:
            while True:
                try:
                    await self.run_now()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._last_error = "scanner_auto_loop_run_failed"
                interval = self._settings.scanner_auto_loop_interval_seconds
                self._next_run_after = self._normalized_now() + timedelta(seconds=interval)
                await asyncio.sleep(interval)
        finally:
            self._next_run_after = None

    def _ensure_enabled(self) -> None:
        if not self._settings.scanner_enabled:
            raise ScannerDisabledError("Scanner is disabled.")
        if not self._settings.scanner_auto_loop_enabled:
            raise ScannerAutoLoopDisabledError("Scanner auto-loop is disabled.")
        if self._settings.scanner_auto_loop_interval_seconds < 1:
            raise ScannerConfigError("Scanner auto-loop interval must be positive.")
        if not self._settings.scanner_auto_loop_candidates_always_persist:
            raise ScannerConfigError("Auto-loop candidates must always persist.")

    def _configured_symbols_or_none(self) -> list[str] | None:
        if self._settings.scanner_auto_loop_use_selected_universe:
            return None
        configured = [
            item.strip()
            for item in self._settings.scanner_auto_loop_symbols.split(",")
            if item.strip()
        ]
        if configured:
            return configured
        if self._settings.scanner_auto_loop_use_market_watchlist:
            return None
        raise ScannerConfigError("Scanner auto-loop symbols are not configured.")

    def _status_symbols(self) -> list[str]:
        configured = [
            item.strip().upper()
            for item in self._settings.scanner_auto_loop_symbols.split(",")
            if item.strip()
        ]
        if configured:
            return configured
        if self._settings.scanner_auto_loop_use_market_watchlist:
            return [item.upper() for item in configured_watchlist_entries(self._settings)]
        return []

    def _time_skip_reason(self, now: datetime) -> str | None:
        local = now.astimezone(IST)
        if self._settings.scanner_auto_loop_run_on_market_days_only and local.weekday() >= 5:
            return "non_market_weekday"
        start = _parse_time(self._settings.scanner_auto_loop_start_after_ist)
        stop = _parse_time(self._settings.scanner_auto_loop_stop_after_ist)
        if local.time() < start:
            return "before_start_time"
        if local.time() > stop:
            return "after_stop_time"
        return None

    def _normalized_now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


def _parse_time(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute)
    except ValueError as exc:
        raise ScannerConfigError("Scanner auto-loop time must be HH:MM.") from exc
