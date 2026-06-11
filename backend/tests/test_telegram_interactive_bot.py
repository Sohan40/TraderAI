from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from app.core.config import Settings
from app.ops.market_ops_scheduler import MarketOpsScheduler
from app.ops.telegram_actions import TelegramActionService
from app.ops.telegram_bot import TelegramInteractiveBot

NOW = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)


def bot_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "market_ops_automation_enabled": True,
        "market_ops_notify_provider": "telegram",
        "market_ops_telegram_bot_token": "telegram-token",
        "market_ops_telegram_interactive_enabled": True,
        "market_ops_telegram_interactive_allowed_chat_id": "123",
        "market_ops_telegram_interactive_allowed_user_id": "456",
        "market_ops_telegram_interactive_poll_seconds": 3600,
        "market_ops_telegram_interactive_max_actions_per_minute": 10,
        "market_ops_telegram_interactive_require_confirmation": True,
        "market_ops_decision_auto_evaluate_max_signals": 5,
    }
    values.update(overrides)
    return Settings(**values)


class FakeKite:
    def __init__(self) -> None:
        self.login_calls = 0

    async def create_login_url(self) -> dict[str, str]:
        self.login_calls += 1
        return {"login_url": f"https://kite.example/fresh-{self.login_calls}"}

    async def get_status(self) -> dict[str, object]:
        return {
            "configured": True,
            "authenticated": True,
            "expired": False,
            "status": "ACTIVE",
            "expires_at": "2026-06-12T06:00:00+05:30",
        }


class FakeStream:
    def __init__(self, **status: object) -> None:
        self.values = {
            "running": False,
            "connected": False,
            "stale": False,
            "configured_symbols": 2,
            "subscribed_symbols": 0,
            "last_tick_at": None,
            "last_error": None,
            **status,
        }

    def status_dict(self) -> dict[str, object]:
        return dict(self.values)


class FakeScheduler:
    def __init__(self, summaries: dict[str, dict[str, object]] | None = None) -> None:
        self.calls: list[str] = []
        self.summaries = summaries or {}
        self.running = False

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "running": self.running,
            "last_error": None,
            "next_scheduled_action": {"action": "scanner_batch"},
        }

    async def start(self) -> dict[str, object]:
        self.running = True
        return self.status()

    async def stop(self) -> dict[str, object]:
        self.running = False
        return self.status()

    async def run_job(self, name: str) -> dict[str, object]:
        self.calls.append(name)
        return self.summaries.get(
            name,
            {
                "ok": True,
                "skipped": False,
                "event": f"{name}_completed",
                "message": "completed",
            },
        )


class FakeDecision:
    async def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "adapter": "fake",
            "evaluation_mode": "LIVE_SHADOW",
            "model_configured": True,
        }


class FakeDecisionAutomation:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def status(self) -> dict[str, object]:
        return {"enabled": False, "evaluation_mode": "LIVE_SHADOW", "last_summary": None}

    async def evaluate_latest(self, *, limit: int) -> dict[str, object]:
        self.limits.append(limit)
        return {"source": "manual_latest", "attempted": 1, "created": 1}


def actions(
    *,
    configured: Settings | None = None,
    scheduler: object | None = None,
    kite: FakeKite | None = None,
    stream: FakeStream | None = None,
    decision_automation: FakeDecisionAutomation | None = None,
) -> TelegramActionService:
    return TelegramActionService(
        settings=configured or bot_settings(),
        kite_service=kite or FakeKite(),
        stream_service=stream or FakeStream(),
        scheduler=scheduler or FakeScheduler(),  # type: ignore[arg-type]
        decision_service=FakeDecision(),
        decision_automation=decision_automation or FakeDecisionAutomation(),
    )


class FakeTelegramSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.updates: list[dict[str, object]] = []

    def __call__(
        self,
        url: str,
        payload: dict[str, object],
        _timeout: float,
    ) -> dict[str, object]:
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, payload))
        if method == "getUpdates":
            return {"ok": True, "result": list(self.updates)}
        return {"ok": True, "result": {}}


def callback(action: str, *, chat_id: str = "123", user_id: str = "456") -> dict[str, object]:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "callback-1",
            "data": action,
            "from": {"id": int(user_id)},
            "message": {"chat": {"id": int(chat_id), "type": "private"}},
        },
    }


@pytest.mark.asyncio
async def test_bot_disabled_by_default_and_start_requires_config() -> None:
    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=Settings(),
        actions=actions(configured=Settings()),
        sender=sender,
    )

    status = await bot.start()

    assert status["enabled"] is False
    assert status["running"] is False
    assert sender.calls == []


@pytest.mark.asyncio
async def test_bot_start_is_idempotent_and_stop_cancels_cleanly() -> None:
    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=bot_settings(),
        actions=actions(),
        sender=sender,
    )

    first = await asyncio.wait_for(bot.start(), timeout=1)
    second = await asyncio.wait_for(bot.start(), timeout=1)
    stopped = await asyncio.wait_for(bot.stop(), timeout=1)

    assert first["running"] is True
    assert second["running"] is True
    assert stopped["running"] is False
    assert [method for method, _ in sender.calls].count("getUpdates") == 1


@pytest.mark.asyncio
async def test_start_message_sends_menu_keyboard() -> None:
    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=bot_settings(),
        actions=actions(),
        sender=sender,
    )

    await bot.handle_update(
        {
            "update_id": 1,
            "message": {
                "text": "/start",
                "from": {"id": 456},
                "chat": {"id": 123, "type": "private"},
            },
        }
    )

    method, payload = sender.calls[-1]
    assert method == "sendMessage"
    assert "inline_keyboard" in payload["reply_markup"]  # type: ignore[operator]
    assert "Start Stream" in str(payload)


@pytest.mark.asyncio
async def test_unknown_chat_user_group_and_action_are_rejected() -> None:
    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=bot_settings(),
        actions=actions(),
        sender=sender,
    )

    await bot.handle_update(callback("ops:stream_status", chat_id="999"))
    await bot.handle_update(callback("ops:stream_status", user_id="999"))
    await bot.handle_update(
        {
            "message": {
                "text": "/menu",
                "from": {"id": 456},
                "chat": {"id": 123, "type": "group"},
            }
        }
    )
    await bot.handle_update(callback("ops:unknown"))

    assert bot.status()["rejected_updates"] == 4
    assert not any(method == "sendMessage" for method, _ in sender.calls)


@pytest.mark.asyncio
async def test_fresh_login_link_is_new_and_not_status_exposed() -> None:
    kite = FakeKite()
    action_service = actions(kite=kite)

    first = await action_service.handle("ops:kite_login")
    second = await action_service.handle("ops:kite_login")

    assert first is not None and "fresh-1" in first.text
    assert second is not None and "fresh-2" in second.text
    assert "kite.example" not in str(action_service.menu())


@pytest.mark.asyncio
async def test_stream_status_is_compact_and_safe() -> None:
    response = await actions(
        stream=FakeStream(running=True, connected=True, last_tick_at="now")
    ).handle("ops:stream_status")

    assert response is not None
    assert "running: True" in response.text
    assert "connected: True" in response.text
    assert "token" not in response.text.lower()


@pytest.mark.asyncio
async def test_start_stream_is_idempotent_for_connected_and_disconnected_streams() -> None:
    connected_scheduler = FakeScheduler(
        {
            "stream_start": {
                "ok": True,
                "skipped": True,
                "event": "stream_started",
                "message": "already running",
                "details": {"connected": True},
            }
        }
    )
    disconnected_scheduler = FakeScheduler(
        {
            "stream_start": {
                "ok": False,
                "skipped": True,
                "event": "stream_not_connected",
                "message": "running",
                "details": {"connected": False},
            }
        }
    )

    connected = await actions(scheduler=connected_scheduler).handle("ops:stream_start")
    disconnected = await actions(scheduler=disconnected_scheduler).handle("ops:stream_start")

    assert connected is not None and connected.text == "Stream already running and connected."
    assert disconnected is not None and "Verify Stream or Stop/Start" in disconnected.text
    assert connected_scheduler.calls == ["stream_start"]
    assert disconnected_scheduler.calls == ["stream_start"]


@pytest.mark.asyncio
async def test_start_stream_busy_does_not_overlap_or_mutate_completed_keys() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingOps:
        async def start_stream_if_ready(self) -> dict[str, object]:
            entered.set()
            await release.wait()
            return {"ok": True, "event": "stream_started", "details": {}}

    scheduler = MarketOpsScheduler(
        settings=bot_settings(),
        orchestrator=BlockingOps(),  # type: ignore[arg-type]
        now_provider=lambda: NOW,
    )
    scheduler._completed_keys.add("2026-06-11:stream_start")
    running = asyncio.create_task(scheduler.run_job("stream_start"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        before = set(scheduler._completed_keys)
        next_before = scheduler.status()["next_scheduled_action"]
        response = await actions(scheduler=scheduler).handle("ops:stream_start")
        after = set(scheduler._completed_keys)
        next_after = scheduler.status()["next_scheduled_action"]
    finally:
        release.set()
        await asyncio.wait_for(running, timeout=1)

    assert response is not None and response.text.startswith("Job already running")
    assert before == after == {"2026-06-11:stream_start"}
    assert next_before == next_after


@pytest.mark.asyncio
async def test_stop_actions_require_confirmation_and_confirm_uses_scheduler_job() -> None:
    scheduler = FakeScheduler()
    service = actions(scheduler=scheduler)

    prompt = await service.handle("ops:stream_stop")
    confirmed = await service.handle("ops:stream_stop_confirm")

    assert prompt is not None and "Confirm Stop Stream" in prompt.text
    assert confirmed is not None
    assert scheduler.calls == ["stream_stop"]


@pytest.mark.asyncio
async def test_emergency_stop_always_requires_confirmation() -> None:
    scheduler = FakeScheduler()
    service = actions(
        configured=bot_settings(
            market_ops_telegram_interactive_require_confirmation=False
        ),
        scheduler=scheduler,
    )

    prompt = await service.handle("ops:emergency_stop")

    assert prompt is not None and "Confirm Emergency Stop Stream" in prompt.text
    assert scheduler.calls == []


@pytest.mark.asyncio
async def test_scanner_and_decision_actions_are_narrow_and_bounded() -> None:
    scheduler = FakeScheduler()
    decision = FakeDecisionAutomation()
    service = actions(scheduler=scheduler, decision_automation=decision)

    await service.handle("ops:scanner")
    await service.handle("ops:p07_evaluate_latest")

    assert scheduler.calls == ["scanner_batch"]
    assert decision.limits == [5]
    assert not hasattr(service, "paper_service")


@pytest.mark.asyncio
async def test_rate_limit_blocks_excess_actions() -> None:
    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=bot_settings(
            market_ops_telegram_interactive_max_actions_per_minute=1
        ),
        actions=actions(),
        sender=sender,
        now_provider=lambda: NOW,
    )

    await bot.handle_update(callback("ops:stream_status"))
    await bot.handle_update(callback("ops:kite_status"))

    assert bot.status()["handled_updates"] == 1
    assert bot.status()["rejected_updates"] == 1
    assert any(
        method == "answerCallbackQuery" and payload.get("text") == "Rate limit reached."
        for method, payload in sender.calls
    )


@pytest.mark.asyncio
async def test_telegram_action_failure_is_contained() -> None:
    class FailingActions:
        async def handle(self, _action: str) -> object:
            raise RuntimeError("failed")

        def menu(self) -> object:
            raise AssertionError

        def help(self) -> object:
            raise AssertionError

    sender = FakeTelegramSender()
    bot = TelegramInteractiveBot(
        settings=bot_settings(),
        actions=FailingActions(),  # type: ignore[arg-type]
        sender=sender,
    )

    await bot.handle_update(callback("ops:stream_status"))

    assert bot.status()["last_error"] == "telegram_action_failed"
    assert any(method == "sendMessage" for method, _ in sender.calls)


def test_telegram_bot_source_has_no_shell_docker_or_execution_capability() -> None:
    from pathlib import Path

    source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (
            Path("backend/app/ops/telegram_bot.py"),
            Path("backend/app/ops/telegram_actions.py"),
        )
    )

    for forbidden in (
        "subprocess",
        "os.system",
        "docker.sock",
        "docker compose",
        "systemctl",
        "place_order",
        "modify_order",
        "cancel_order",
        "kiteticker",
        "paper.replay",
    ):
        assert forbidden not in source
