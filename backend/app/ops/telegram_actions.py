"""Allowlisted interactive Telegram operator actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.ops.market_ops_scheduler import (
    MarketOpsAutomationDisabledError,
    MarketOpsJobBusyError,
)


class KiteActions(Protocol):
    async def create_login_url(self) -> dict[str, str]: ...
    async def get_status(self) -> dict[str, object]: ...


class StreamStatus(Protocol):
    def status_dict(self) -> dict[str, object]: ...


class SchedulerActions(Protocol):
    def status(self) -> dict[str, object]: ...
    async def start(self) -> dict[str, object]: ...
    async def stop(self) -> dict[str, object]: ...
    async def run_job(self, name: str) -> dict[str, object]: ...


class DecisionStatus(Protocol):
    async def status(self) -> dict[str, object]: ...


class DecisionAutomation(Protocol):
    def status(self) -> dict[str, object]: ...
    async def evaluate_latest(self, *, limit: int) -> dict[str, object]: ...


@dataclass(frozen=True)
class TelegramActionResponse:
    text: str
    keyboard: list[list[tuple[str, str]]] | None = None


MENU_KEYBOARD = [
    [("Fresh Kite Login Link", "ops:kite_login"), ("Kite Status", "ops:kite_status")],
    [
        ("Stream Status", "ops:stream_status"),
        ("Start Stream", "ops:stream_start"),
        ("Verify Stream", "ops:stream_verify"),
        ("Stop Stream", "ops:stream_stop"),
    ],
    [
        ("Scheduler Status", "ops:scheduler_status"),
        ("Start Scheduler", "ops:scheduler_start"),
        ("Stop Scheduler", "ops:scheduler_stop"),
    ],
    [
        ("Run Preopen", "ops:preopen"),
        ("Run Universe", "ops:universe"),
        ("Run Scanner", "ops:scanner"),
    ],
    [
        ("P07 Status", "ops:p07_status"),
        ("P07 Auto Status", "ops:p07_auto_status"),
        ("Evaluate Latest", "ops:p07_evaluate_latest"),
    ],
    [("Emergency Stop Stream", "ops:emergency_stop"), ("Help", "ops:help")],
]

_CONFIRMATIONS = {
    "ops:stream_stop": ("Stop Stream", "ops:stream_stop_confirm"),
    "ops:scheduler_stop": ("Stop Scheduler", "ops:scheduler_stop_confirm"),
    "ops:emergency_stop": ("Emergency Stop Stream", "ops:emergency_stop_confirm"),
}


class TelegramActionService:
    """Map static Telegram callbacks to existing safe services only."""

    def __init__(
        self,
        *,
        settings: Settings,
        kite_service: KiteActions,
        stream_service: StreamStatus,
        scheduler: SchedulerActions,
        decision_service: DecisionStatus,
        decision_automation: DecisionAutomation,
    ) -> None:
        self._settings = settings
        self._kite_service = kite_service
        self._stream_service = stream_service
        self._scheduler = scheduler
        self._decision_service = decision_service
        self._decision_automation = decision_automation

    def menu(self) -> TelegramActionResponse:
        return TelegramActionResponse(
            text="TraderAI operator menu. Trading and paper execution remain disabled.",
            keyboard=MENU_KEYBOARD,
        )

    def help(self) -> TelegramActionResponse:
        return TelegramActionResponse(
            text=(
                "Available actions are limited to Kite login/status, read-only stream "
                "operations, scheduler controls, scanner jobs, and P07 shadow evaluation. "
                "The bot cannot place orders, run paper replay, execute shell commands, "
                "or restart the API."
            ),
            keyboard=MENU_KEYBOARD,
        )

    async def handle(self, action: str) -> TelegramActionResponse | None:
        if action == "ops:help":
            return self.help()
        confirmation_required = (
            action == "ops:emergency_stop"
            or self._settings.market_ops_telegram_interactive_require_confirmation
        )
        if action in _CONFIRMATIONS and confirmation_required:
            label, confirm_action = _CONFIRMATIONS[action]
            return TelegramActionResponse(
                text=f"Confirm {label}?",
                keyboard=[[("Confirm", confirm_action), ("Cancel", "ops:cancel")]],
            )
        if action == "ops:cancel":
            return TelegramActionResponse("Action cancelled.", MENU_KEYBOARD)
        if action == "ops:kite_login":
            response = await self._kite_service.create_login_url()
            url = response.get("login_url", "")
            return TelegramActionResponse(
                "Fresh Kite login link:\n" + url if url else "Kite login link unavailable."
            )
        if action == "ops:kite_status":
            return TelegramActionResponse(_format_kite_status(await self._kite_service.get_status()))
        if action == "ops:stream_status":
            return TelegramActionResponse(_format_stream_status(self._stream_service.status_dict()))
        if action == "ops:stream_start":
            return await self._run_job("stream_start")
        if action == "ops:stream_verify":
            return await self._run_job("stream_verify")
        if action in {
            "ops:stream_stop",
            "ops:stream_stop_confirm",
            "ops:emergency_stop",
            "ops:emergency_stop_confirm",
        }:
            return await self._run_job("stream_stop")
        if action == "ops:scheduler_status":
            return TelegramActionResponse(_format_scheduler_status(self._scheduler.status()))
        if action == "ops:scheduler_start":
            try:
                return TelegramActionResponse(
                    _format_scheduler_status(await self._scheduler.start())
                )
            except MarketOpsAutomationDisabledError:
                return TelegramActionResponse("Scheduler is disabled by configuration.")
        if action in {"ops:scheduler_stop", "ops:scheduler_stop_confirm"}:
            return TelegramActionResponse(_format_scheduler_status(await self._scheduler.stop()))
        if action == "ops:preopen":
            return await self._run_job("preopen_check")
        if action == "ops:universe":
            return await self._run_job("universe_selection")
        if action == "ops:scanner":
            return await self._run_job("scanner_batch")
        if action == "ops:p07_status":
            return TelegramActionResponse(_format_decision_status(await self._decision_service.status()))
        if action == "ops:p07_auto_status":
            return TelegramActionResponse(_format_decision_status(self._decision_automation.status()))
        if action == "ops:p07_evaluate_latest":
            maximum = max(1, min(self._settings.market_ops_decision_auto_evaluate_max_signals, 50))
            return TelegramActionResponse(
                _format_job_summary(await self._decision_automation.evaluate_latest(limit=maximum))
            )
        return None

    async def _run_job(self, name: str) -> TelegramActionResponse:
        try:
            summary = await self._scheduler.run_job(name)
        except MarketOpsJobBusyError:
            return TelegramActionResponse("Job already running. No overlapping action started.")
        if name == "stream_start":
            event = summary.get("event")
            details = summary.get("details")
            safe_details = details if isinstance(details, dict) else {}
            if summary.get("skipped") and event == "stream_started":
                return TelegramActionResponse("Stream already running and connected.")
            if event == "stream_not_connected":
                return TelegramActionResponse(
                    "Stream is running but not connected. Use Verify Stream or Stop/Start."
                )
            if event == "stream_start_skipped":
                action = safe_details.get("recommended_action")
                suffix = f" Suggested action: {action}." if action else ""
                return TelegramActionResponse("Stream start blocked by readiness gates." + suffix)
        return TelegramActionResponse(_format_job_summary(summary))


def _format_kite_status(status: dict[str, object]) -> str:
    return "\n".join(
        [
            "Kite status",
            f"configured: {bool(status.get('configured'))}",
            f"authenticated: {bool(status.get('authenticated'))}",
            f"expired: {bool(status.get('expired'))}",
            f"status: {status.get('status')}",
            f"expires_at: {status.get('expires_at')}",
        ]
    )


def _format_stream_status(status: dict[str, object]) -> str:
    fields = (
        "running",
        "connected",
        "stale",
        "configured_symbols",
        "subscribed_symbols",
        "last_tick_at",
        "last_error",
    )
    return "Stream status\n" + "\n".join(f"{key}: {status.get(key)}" for key in fields)


def _format_scheduler_status(status: dict[str, object]) -> str:
    return "\n".join(
        [
            "Scheduler status",
            f"enabled: {status.get('enabled')}",
            f"running: {status.get('running')}",
            f"last_error: {status.get('last_error')}",
            f"next_action: {status.get('next_scheduled_action')}",
        ]
    )


def _format_decision_status(status: dict[str, object]) -> str:
    fields = ("enabled", "adapter", "evaluation_mode", "model_configured", "last_summary")
    return "P07 status\n" + "\n".join(f"{key}: {status.get(key)}" for key in fields)


def _format_job_summary(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            f"event: {summary.get('event', summary.get('source', 'completed'))}",
            f"ok: {summary.get('ok', True)}",
            f"skipped: {summary.get('skipped', False)}",
            f"message: {summary.get('message', '')}",
        ]
    )
