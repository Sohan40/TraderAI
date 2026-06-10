"""Disabled-by-default process-local market operations scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.ops.market_ops import MarketOpsOrchestrator


class MarketOpsAutomationDisabledError(RuntimeError):
    """Raised when an operator tries to start disabled automation."""


class MarketOpsJobBusyError(RuntimeError):
    """Raised when a market-ops job is already running."""


class MarketOpsScheduler:
    """Run explicit local market-ops jobs on a conservative daily schedule."""

    def __init__(
        self,
        *,
        settings: Settings,
        orchestrator: MarketOpsOrchestrator,
        now_provider: Callable[[], datetime] | None = None,
        poll_seconds: float = 5.0,
    ) -> None:
        self._settings = settings
        self._orchestrator = orchestrator
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._job_lock = asyncio.Lock()
        self._completed_keys: set[str] = set()
        self._last_event_at: datetime | None = None
        self._last_error: str | None = None
        self._last: dict[str, dict[str, object] | None] = {
            "preopen_check": None,
            "stream_start": None,
            "stream_verify": None,
            "universe_selection": None,
            "scanner_batch": None,
            "stream_stop": None,
        }
        self._waiting_for_kite_login = False
        self._pending_action: str | None = None
        self._recovery_attempts = 0
        self._recovery_last_attempt_at: datetime | None = None
        self._recovery_next_retry_at: datetime | None = None
        self._login_link_sent = False

    async def start(self) -> dict[str, object]:
        if not self._settings.market_ops_automation_enabled:
            raise MarketOpsAutomationDisabledError("Market operations automation is disabled.")
        async with self._lifecycle_lock:
            if self._task is None or self._task.done():
                self._prepare_late_start_recovery()
                self._task = asyncio.create_task(self._loop(), name="market-ops-scheduler")
                await self._notify_event(
                    event="market_ops_started",
                    level="info",
                    message="Market operations scheduler started.",
                )
        return self.status()

    async def stop(self) -> dict[str, object]:
        async with self._lifecycle_lock:
            task = self._task
            self._task = None
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                await self._notify_event(
                    event="market_ops_stopped",
                    level="info",
                    message="Market operations scheduler stopped.",
                )
        return self.status()

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._settings.market_ops_automation_enabled,
            "running": self._task is not None and not self._task.done(),
            "timezone": self._settings.market_ops_timezone,
            "notification_enabled": self._settings.market_ops_notify_enabled,
            "notification_provider": self._settings.market_ops_notify_provider,
            "autostart_enabled": self._settings.market_ops_autostart_enabled,
            "last_event_at": self._last_event_at.isoformat() if self._last_event_at else None,
            "last_error": self._last_error,
            "login_recovery_enabled": self._settings.market_ops_login_recovery_enabled,
            "waiting_for_kite_login": self._waiting_for_kite_login,
            "pending_action": self._pending_action,
            "recovery_attempts": self._recovery_attempts,
            "recovery_last_attempt_at": (
                self._recovery_last_attempt_at.isoformat()
                if self._recovery_last_attempt_at
                else None
            ),
            "recovery_next_retry_at": (
                self._recovery_next_retry_at.isoformat()
                if self._recovery_next_retry_at
                else None
            ),
            "recovery_window": {
                "start": self._settings.market_ops_login_recovery_start_ist,
                "stop": self._settings.market_ops_login_recovery_stop_ist,
                "interval_seconds": self._settings.market_ops_login_recovery_interval_seconds,
            },
            "last_preopen_check": self._last["preopen_check"],
            "last_stream_start": self._last["stream_start"],
            "last_stream_verify": self._last["stream_verify"],
            "last_universe_selection": self._last["universe_selection"],
            "last_scanner_batch": self._last["scanner_batch"],
            "last_stream_stop": self._last["stream_stop"],
            "next_scheduled_action": (
                self._next_scheduled_action()
                if self._settings.market_ops_automation_enabled
                else None
            ),
            "schedule": self._schedule(),
            "overlap_prevention": True,
        }

    async def run_job(self, name: str) -> dict[str, object]:
        if self._job_lock.locked():
            raise MarketOpsJobBusyError("A market operations job is already running.")
        method_name = {
            "preopen_check": "preopen_check",
            "stream_start": "start_stream_if_ready",
            "stream_verify": "verify_stream",
            "universe_selection": "run_universe_selection",
            "scanner_batch": "run_scanner_batch",
            "stream_stop": "stop_stream",
        }.get(name)
        if method_name is None:
            raise ValueError("Unsupported market operations job.")
        job = getattr(self._orchestrator, method_name)
        async with self._job_lock:
            try:
                summary = await job()
                self._last[name] = summary
                self._last_error = None if summary.get("ok") else str(summary.get("event"))
                self._last_event_at = self._now()
                await self._process_recovery_summary(name, summary)
                return summary
            except Exception:
                self._last_error = "market_ops_job_failed"
                self._last_event_at = self._now()
                await self._notify_event(
                    event="market_ops_job_failed",
                    level="error",
                    message="Market operations job failed.",
                    details={"job": name},
                )
                return {
                    "ok": False,
                    "skipped": False,
                    "event": "market_ops_job_failed",
                    "level": "error",
                    "message": "Market operations job failed.",
                    "started_at": self._last_event_at.isoformat(),
                    "finished_at": self._last_event_at.isoformat(),
                    "details": {"job": name},
                }

    async def _loop(self) -> None:
        while True:
            try:
                await self._run_due_job()
                await self._run_recovery()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error = "market_ops_scheduler_tick_failed"
                self._last_event_at = self._now()
                await self._notify_event(
                    event="market_ops_job_failed",
                    level="error",
                    message="Market operations scheduler tick failed.",
                    details={},
                )
            await asyncio.sleep(self._poll_seconds)

    async def _process_recovery_summary(
        self,
        name: str,
        summary: dict[str, object],
    ) -> None:
        details = summary.get("details")
        safe_details = details if isinstance(details, dict) else {}
        login_missing = (
            summary.get("event") == "kite_session_missing"
            or safe_details.get("recommended_action") == "login_kite"
        )
        if name in {"preopen_check", "stream_start"} and login_missing:
            await self._arm_login_recovery()
            return
        if self._pending_action is None:
            return
        if name == "stream_start":
            self._waiting_for_kite_login = False
            if summary.get("event") in {"stream_started", "stream_not_connected"}:
                self._pending_action = "stream_verify"
            self._schedule_next_recovery()
        elif name == "stream_verify":
            if bool(summary.get("ok")):
                self._clear_recovery()
            else:
                self._schedule_next_recovery()

    async def _arm_login_recovery(self) -> None:
        new_episode = self._pending_action is None
        self._waiting_for_kite_login = True
        self._pending_action = "stream_start"
        self._schedule_next_recovery()
        if new_episode:
            self._recovery_attempts = 0
            self._login_link_sent = False
        if not self._login_link_sent:
            self._login_link_sent = True
            send_link = getattr(self._orchestrator, "send_kite_login_link", None)
            if send_link is not None:
                await send_link()

    def _prepare_late_start_recovery(self) -> None:
        if not self._settings.market_ops_login_recovery_enabled:
            return
        now = self._local_now()
        if not self._inside_recovery_window(now):
            return
        self._waiting_for_kite_login = False
        self._pending_action = "stream_start"
        self._recovery_attempts = 0
        self._recovery_last_attempt_at = None
        self._recovery_next_retry_at = self._now()
        self._login_link_sent = False

    async def _run_recovery(self) -> None:
        if self._pending_action is None:
            return
        local_now = self._local_now()
        if self._recovery_window_expired(local_now):
            if self._settings.market_ops_login_recovery_enabled:
                await self._notify_event(
                    event="kite_login_recovery_expired",
                    level="warning",
                    message="Automatic stream start was not completed inside the recovery window.",
                    details={"pending_action": self._pending_action},
                )
            self._clear_recovery()
            return
        if (
            not self._settings.market_ops_login_recovery_enabled
            or not self._inside_recovery_window(local_now)
            or self._job_lock.locked()
        ):
            return
        now = self._now()
        if self._recovery_next_retry_at is not None and now < self._recovery_next_retry_at:
            return
        action = self._pending_action
        self._recovery_attempts += 1
        self._recovery_last_attempt_at = now
        self._schedule_next_recovery()
        await self.run_job(action)

    def _schedule_next_recovery(self) -> None:
        seconds = max(1, self._settings.market_ops_login_recovery_interval_seconds)
        candidate = self._now() + timedelta(seconds=seconds)
        local_now = self._local_now()
        start = datetime.combine(
            local_now.date(),
            _parse_time(self._settings.market_ops_login_recovery_start_ist),
            tzinfo=local_now.tzinfo,
        )
        start_utc = start.astimezone(timezone.utc)
        self._recovery_next_retry_at = max(candidate, start_utc)

    def _inside_recovery_window(self, now: datetime) -> bool:
        current = now.time().replace(tzinfo=None)
        start = _parse_time(self._settings.market_ops_login_recovery_start_ist)
        stop = _parse_time(self._settings.market_ops_login_recovery_stop_ist)
        return start <= current <= stop

    def _recovery_window_expired(self, now: datetime) -> bool:
        stop = _parse_time(self._settings.market_ops_login_recovery_stop_ist)
        return now.time().replace(tzinfo=None) > stop

    def _clear_recovery(self) -> None:
        self._waiting_for_kite_login = False
        self._pending_action = None
        self._recovery_attempts = 0
        self._recovery_last_attempt_at = None
        self._recovery_next_retry_at = None
        self._login_link_sent = False

    async def _notify_event(
        self,
        *,
        event: str,
        level: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        notify = getattr(self._orchestrator, "notify_scheduler_event", None)
        if notify is None:
            return
        try:
            await notify(
                event=event,
                level=level,
                message=message,
                details=details or {},
            )
        except Exception:
            self._last_error = "market_ops_notification_failed"

    async def _run_due_job(self) -> None:
        now = self._local_now()
        due = self._due_job(now)
        if due is None:
            return
        name, key = due
        if key in self._completed_keys or self._job_lock.locked():
            return
        self._completed_keys.add(key)
        await self.run_job(name)
        self._completed_keys = {
            item for item in self._completed_keys if item.startswith(now.date().isoformat())
        }

    def _due_job(self, now: datetime) -> tuple[str, str] | None:
        one_shots = (
            ("preopen_check", self._settings.market_ops_preopen_check_time),
            ("stream_start", self._settings.market_ops_stream_start_time),
            ("stream_verify", self._settings.market_ops_stream_verify_time),
            ("universe_selection", self._settings.market_ops_universe_select_time),
            ("stream_stop", self._settings.market_ops_stream_stop_time),
        )
        for name, configured in one_shots:
            if _same_minute(now.time(), _parse_time(configured)):
                return name, f"{now.date().isoformat()}:{name}"

        start = _parse_time(self._settings.market_ops_scanner_start_time)
        stop = _parse_time(self._settings.market_ops_scanner_stop_time)
        if start <= now.time().replace(tzinfo=None) <= stop:
            seconds = self._settings.market_ops_scanner_interval_seconds
            if seconds < 1:
                return None
            start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
            elapsed = int((now - start_at).total_seconds())
            slot = elapsed // seconds
            slot_at = start_at + timedelta(seconds=slot * seconds)
            if 0 <= (now - slot_at).total_seconds() < self._poll_seconds:
                return "scanner_batch", f"{now.date().isoformat()}:scanner_batch:{slot}"
        return None

    def _next_scheduled_action(self) -> dict[str, str] | None:
        now = self._local_now()
        candidates: list[tuple[datetime, str]] = []
        for name, configured in (
            ("preopen_check", self._settings.market_ops_preopen_check_time),
            ("stream_start", self._settings.market_ops_stream_start_time),
            ("stream_verify", self._settings.market_ops_stream_verify_time),
            ("universe_selection", self._settings.market_ops_universe_select_time),
            ("scanner_batch", self._settings.market_ops_scanner_start_time),
            ("stream_stop", self._settings.market_ops_stream_stop_time),
        ):
            candidate = datetime.combine(now.date(), _parse_time(configured), tzinfo=now.tzinfo)
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append((candidate, name))
        scheduled_at, name = min(candidates)
        return {"action": name, "scheduled_at": scheduled_at.isoformat()}

    def _schedule(self) -> dict[str, object]:
        return {
            "preopen_check": self._settings.market_ops_preopen_check_time,
            "stream_start": self._settings.market_ops_stream_start_time,
            "stream_verify": self._settings.market_ops_stream_verify_time,
            "universe_selection": self._settings.market_ops_universe_select_time,
            "scanner_start": self._settings.market_ops_scanner_start_time,
            "scanner_interval_seconds": self._settings.market_ops_scanner_interval_seconds,
            "scanner_stop": self._settings.market_ops_scanner_stop_time,
            "stream_stop": self._settings.market_ops_stream_stop_time,
        }

    def _local_now(self) -> datetime:
        zone: tzinfo
        try:
            zone = ZoneInfo(self._settings.market_ops_timezone)
        except ZoneInfoNotFoundError:
            zone = (
                timezone(timedelta(hours=5, minutes=30))
                if self._settings.market_ops_timezone == "Asia/Kolkata"
                else timezone.utc
            )
        return self._now().astimezone(zone)

    def _now(self) -> datetime:
        now = self._now_provider()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _parse_time(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour, minute)
    except ValueError as exc:
        raise ValueError("Market operations time must be HH:MM.") from exc


def _same_minute(current: time, expected: time) -> bool:
    return current.hour == expected.hour and current.minute == expected.minute
