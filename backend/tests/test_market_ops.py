from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import (
    get_market_ops_orchestrator,
    get_market_ops_scheduler,
)
from app.core.config import Settings
from app.main import app
from app.main import lifespan as app_lifespan
from app.ops.market_ops import MarketOpsOrchestrator
from app.ops.market_ops_scheduler import (
    MarketOpsAutomationDisabledError,
    MarketOpsJobBusyError,
    MarketOpsScheduler,
)
from app.ops.notifier import MAX_MESSAGE_LENGTH, Notifier
from app.scanners.schemas import ScannerBatchResult, ScannerSymbolResult
from app.universe.exceptions import SelectedUniverseMissingError
from app.universe.schemas import UniverseSelectionRun

NOW = datetime(2026, 6, 11, 3, 25, tzinfo=timezone.utc)


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def notify(self, **payload: object) -> Any:
        self.calls.append(payload)
        return type(
            "Result",
            (),
            {"ok": True, "skipped": False, "provider": "fake", "event": payload["event"], "error": None},
        )()

    async def test_notification(self) -> Any:
        return type(
            "Result",
            (),
            {
                "ok": True,
                "skipped": False,
                "provider": "fake",
                "event": "market_ops_test_notification",
                "error": None,
            },
        )()


class FakeLoginUrlProvider:
    def __init__(self, url: str = "https://kite.example/login?state=safe-state") -> None:
        self.url = url
        self.calls = 0

    async def create_login_url(self) -> dict[str, str]:
        self.calls += 1
        return {"login_url": self.url}


class FakeMorning:
    def __init__(self, *, kite_ready: bool = True, watchlist_ready: bool = True) -> None:
        self.kite_ready = kite_ready
        self.watchlist_ready = watchlist_ready

    async def readiness(self) -> dict[str, object]:
        return {
            "safe": True,
            "stream_readiness": {"kite_session_ready": self.kite_ready},
            "watchlist_validation": {"ready_for_stream": self.watchlist_ready},
        }


class FakeReadiness:
    def __init__(self, **values: object) -> None:
        self.values: dict[str, object] = {
            "kite_session_ready": True,
            "watchlist_ready": True,
            "can_start_stream": True,
            "stream_already_running": False,
            "stream_connected": False,
            "configured_symbols": 2,
            "subscribed_symbols": 0,
            "last_error": None,
            "errors": [],
            "missing_symbols": [],
            "recommended_next_action": "ready_to_start_stream",
        }
        self.values.update(values)

    async def readiness(self) -> dict[str, object]:
        return dict(self.values)


class FakeStream:
    def __init__(self, *, running: bool = False, stale: bool = False) -> None:
        self.running = running
        self.stale = stale
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> dict[str, object]:
        self.start_calls += 1
        self.running = True
        return {
            "running": True,
            "connected": False,
            "configured_symbols": 2,
            "subscribed_symbols": 0,
            "last_error": None,
        }

    async def stop(self) -> dict[str, object]:
        self.stop_calls += 1
        self.running = False
        return {
            "running": False,
            "connected": False,
            "configured_symbols": 2,
            "subscribed_symbols": 0,
            "last_error": None,
        }

    def status_dict(self) -> dict[str, object]:
        return {"running": self.running, "connected": self.running, "stale": self.stale}


class FakeUniverse:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def select(self, **kwargs: object) -> UniverseSelectionRun:
        self.calls.append(kwargs)
        return _universe_run()


class FakeScanner:
    def __init__(self, *, missing: bool = False, candidates: int = 1) -> None:
        self.calls: list[dict[str, object]] = []
        self.missing = missing
        self.candidates = candidates

    async def run_batch(self, **kwargs: object) -> ScannerBatchResult:
        self.calls.append(kwargs)
        if self.missing:
            raise SelectedUniverseMissingError("Selected universe missing.")
        return ScannerBatchResult(
            evaluated_symbols=1,
            total_evaluated=2,
            total_inserted=self.candidates,
            total_duplicates=0,
            total_candidates=self.candidates,
            total_rejected=1,
            per_symbol=[
                ScannerSymbolResult(
                    symbol="NSE:SBIN",
                    evaluated=2,
                    inserted=self.candidates,
                    candidates=self.candidates,
                    rejected=1,
                )
            ],
            errors={},
            started_at=NOW,
            finished_at=NOW,
        )


def ops_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "trading_mode": "OFF",
        "live_armed": False,
        "market_ops_automation_enabled": True,
        "market_ops_notify_enabled": False,
        "market_ops_notify_provider": "none",
        "universe_selection_enabled": True,
        "scanner_enabled": True,
        "market_data_watchlist": "NSE:SBIN",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def orchestrator(
    *,
    settings: Settings | None = None,
    morning: FakeMorning | None = None,
    readiness: FakeReadiness | None = None,
    stream: FakeStream | None = None,
    universe: FakeUniverse | None = None,
    scanner: FakeScanner | None = None,
    notifier: FakeNotifier | None = None,
    login_provider: FakeLoginUrlProvider | None = None,
) -> MarketOpsOrchestrator:
    return MarketOpsOrchestrator(
        settings=settings or ops_settings(),
        morning_readiness=morning or FakeMorning(),
        stream_readiness=readiness or FakeReadiness(),
        stream_service=stream or FakeStream(),
        universe_service=universe or FakeUniverse(),
        scanner_service=scanner or FakeScanner(),
        notifier=notifier or FakeNotifier(),  # type: ignore[arg-type]
        kite_login_url_provider=login_provider,
        now_provider=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_none_notifier_skips_safely() -> None:
    result = await Notifier(settings=Settings()).notify(
        level="warning",
        event="watchlist_not_ready",
        message="Watchlist is not ready.",
    )

    assert result.ok is True
    assert result.skipped is True
    assert result.provider == "none"


@pytest.mark.asyncio
async def test_telegram_notifier_builds_payload_without_exposing_token() -> None:
    sent: dict[str, object] = {}

    def sender(url: str, payload: bytes, timeout: float) -> None:
        sent.update(url=url, payload=payload, timeout=timeout)

    notifier = Notifier(
        settings=ops_settings(
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
            market_ops_telegram_bot_token="fake-token",
            market_ops_telegram_chat_id="12345",
            market_ops_notify_min_level="info",
        ),
        http_sender=sender,
        now_provider=lambda: NOW,
    )

    result = await notifier.notify(
        level="warning",
        event="kite_session_missing",
        message="Login required.",
        details={"recommended_action": "login_kite", "api_secret": "hidden"},
    )
    sent_payload = sent["payload"]
    assert isinstance(sent_payload, bytes)
    payload = parse_qs(sent_payload.decode())

    assert result.as_dict() == {
        "ok": True,
        "skipped": False,
        "provider": "telegram",
        "event": "kite_session_missing",
        "error": None,
    }
    assert payload["chat_id"] == ["12345"]
    assert "kite_session_missing" in payload["text"][0]
    assert "api_secret" not in payload["text"][0]
    assert "fake-token" not in str(result.as_dict())
    assert sent["timeout"] == 5.0


@pytest.mark.asyncio
async def test_telegram_notifier_requires_config_and_contains_failures() -> None:
    missing = await Notifier(
        settings=ops_settings(
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
        )
    ).notify(level="error", event="market_ops_job_failed", message="Failure.")
    failed = await Notifier(
        settings=ops_settings(
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
            market_ops_telegram_bot_token="fake-token",
            market_ops_telegram_chat_id="123",
        ),
        http_sender=lambda *_args: (_ for _ in ()).throw(OSError("offline")),
    ).notify(level="error", event="market_ops_job_failed", message="Failure.")

    assert missing.error == "telegram_not_configured"
    assert failed.error == "telegram_send_failed"


@pytest.mark.asyncio
async def test_notifier_filters_levels_and_truncates_message() -> None:
    sent: list[bytes] = []
    notifier = Notifier(
        settings=ops_settings(
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
            market_ops_telegram_bot_token="fake-token",
            market_ops_telegram_chat_id="123",
            market_ops_notify_min_level="error",
        ),
        http_sender=lambda _url, payload, _timeout: sent.append(payload),
    )

    filtered = await notifier.notify(level="warning", event="warning", message="skip")
    delivered = await notifier.notify(
        level="error",
        event="error",
        message="x" * (MAX_MESSAGE_LENGTH + 500),
    )

    assert filtered.skipped is True
    assert delivered.ok is True
    assert len(sent) == 1
    assert len(parse_qs(sent[0].decode())["text"][0]) == MAX_MESSAGE_LENGTH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kite_ready", "watchlist_ready", "event"),
    [
        (False, True, "kite_session_missing"),
        (True, False, "watchlist_not_ready"),
        (True, True, "preopen_check_ok"),
    ],
)
async def test_preopen_check_reports_readiness(
    kite_ready: bool,
    watchlist_ready: bool,
    event: str,
) -> None:
    notifier = FakeNotifier()
    result = await orchestrator(
        morning=FakeMorning(kite_ready=kite_ready, watchlist_ready=watchlist_ready),
        notifier=notifier,
    ).preopen_check()

    assert result["event"] == event
    assert notifier.calls[-1]["event"] == event


@pytest.mark.asyncio
async def test_kite_login_link_is_gated_and_contains_no_secrets() -> None:
    disabled_provider = FakeLoginUrlProvider()
    disabled = await orchestrator(
        settings=ops_settings(
            market_ops_send_kite_login_link=False,
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
            kite_auth_enabled=True,
            kite_api_key="api-key",
            kite_api_secret="api-secret",
            kite_redirect_url="https://example.test/callback",
            operator_auth_token="operator-secret",
        ),
        login_provider=disabled_provider,
    ).send_kite_login_link()
    notifier = FakeNotifier()
    enabled_provider = FakeLoginUrlProvider()
    enabled = await orchestrator(
        settings=ops_settings(
            market_ops_send_kite_login_link=True,
            market_ops_notify_enabled=True,
            market_ops_notify_provider="telegram",
            kite_auth_enabled=True,
            kite_api_key="api-key",
            kite_api_secret="api-secret",
            kite_redirect_url="https://example.test/callback",
            operator_auth_token="operator-secret",
        ),
        notifier=notifier,
        login_provider=enabled_provider,
    ).send_kite_login_link()

    assert disabled is False
    assert disabled_provider.calls == 0
    assert enabled is True
    assert enabled_provider.calls == 1
    assert notifier.calls[-1]["event"] == "kite_login_link_sent"
    notification = str(notifier.calls[-1])
    assert "https://kite.example/login?state=safe-state" in notification
    assert "api-secret" not in notification
    assert "operator-secret" not in notification
    assert "access_token" not in notification


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("readiness", "expected_action"),
    [
        (FakeReadiness(kite_session_ready=False), "login_kite"),
        (
            FakeReadiness(
                watchlist_ready=False,
                recommended_next_action="run_instrument_sync",
            ),
            "run_instrument_sync",
        ),
    ],
)
async def test_stream_start_skips_failed_readiness(
    readiness: FakeReadiness,
    expected_action: str,
) -> None:
    stream = FakeStream()
    result = await orchestrator(readiness=readiness, stream=stream).start_stream_if_ready()

    assert result["skipped"] is True
    assert result["details"]["recommended_action"] == expected_action  # type: ignore[index]
    assert stream.start_calls == 0


@pytest.mark.asyncio
async def test_stream_start_calls_existing_service_only_when_ready() -> None:
    stream = FakeStream()

    result = await orchestrator(stream=stream).start_stream_if_ready()

    assert result["event"] == "stream_started"
    assert stream.start_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "readiness",
    [
        FakeReadiness(
            can_start_stream=False,
            stream_already_running=True,
            stream_connected=False,
            subscribed_symbols=2,
        ),
        FakeReadiness(
            can_start_stream=False,
            stream_already_running=True,
            stream_connected=True,
            subscribed_symbols=1,
        ),
    ],
)
async def test_verify_stream_reports_disconnected_or_subscription_mismatch(
    readiness: FakeReadiness,
) -> None:
    result = await orchestrator(readiness=readiness).verify_stream()

    assert result["ok"] is False
    assert result["event"] == "stream_not_connected"


@pytest.mark.asyncio
async def test_verify_stream_reports_stale_candle_health() -> None:
    readiness = FakeReadiness(
        can_start_stream=False,
        stream_already_running=True,
        stream_connected=True,
        subscribed_symbols=2,
    )

    result = await orchestrator(
        readiness=readiness,
        stream=FakeStream(running=True, stale=True),
    ).verify_stream()

    assert result["event"] == "candle_health_warning"
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_universe_selection_disabled_and_success_paths() -> None:
    disabled_ops = await orchestrator(
        settings=ops_settings(market_ops_use_universe_selection=False)
    ).run_universe_selection()
    disabled_universe = await orchestrator(
        settings=ops_settings(universe_selection_enabled=False)
    ).run_universe_selection()
    universe = FakeUniverse()
    success = await orchestrator(universe=universe).run_universe_selection()

    assert disabled_ops["skipped"] is True
    assert disabled_universe["level"] == "warning"
    assert success["details"]["selected_symbols"] == ["NSE:SBIN"]  # type: ignore[index]
    assert universe.calls[0]["stale_policy"] == "exclude"
    assert universe.calls[0]["min_candles"] == 51


@pytest.mark.asyncio
async def test_scanner_batch_source_candidates_and_missing_selection() -> None:
    selected = FakeScanner(candidates=1)
    selected_result = await orchestrator(scanner=selected).run_scanner_batch()
    watchlist = FakeScanner(candidates=0)
    watchlist_result = await orchestrator(
        settings=ops_settings(market_ops_use_selected_universe_for_scanner=False),
        scanner=watchlist,
    ).run_scanner_batch()
    missing = await orchestrator(scanner=FakeScanner(missing=True)).run_scanner_batch()

    assert selected.calls[0]["use_latest_universe"] is True
    assert selected_result["details"]["total_candidates"] == 1  # type: ignore[index]
    assert watchlist.calls[0]["use_latest_universe"] is False
    assert watchlist_result["details"]["symbol_source"] == "market_watchlist"  # type: ignore[index]
    assert missing["skipped"] is True


@pytest.mark.asyncio
async def test_stop_stream_calls_service_and_is_idempotent() -> None:
    running = FakeStream(running=True)
    stopped = await orchestrator(stream=running).stop_stream()
    stopped_again = await orchestrator(stream=running).stop_stream()

    assert stopped["skipped"] is False
    assert stopped_again["skipped"] is True
    assert running.stop_calls == 1


@pytest.mark.asyncio
async def test_scheduler_disabled_start_and_idempotent_stop() -> None:
    scheduler = MarketOpsScheduler(
        settings=ops_settings(market_ops_automation_enabled=False),
        orchestrator=orchestrator(),
        now_provider=lambda: NOW,
    )

    with pytest.raises(MarketOpsAutomationDisabledError):
        await scheduler.start()
    status = await scheduler.stop()
    assert status["running"] is False
    assert status["next_scheduled_action"] is None


@pytest.mark.asyncio
async def test_scheduler_start_status_stop_and_last_summary() -> None:
    notifier = FakeNotifier()
    scheduler = MarketOpsScheduler(
        settings=ops_settings(),
        orchestrator=orchestrator(notifier=notifier),
        now_provider=lambda: datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc),
        poll_seconds=3600,
    )

    try:
        started = await asyncio.wait_for(scheduler.start(), timeout=1)
        summary = await asyncio.wait_for(
            scheduler.run_job("preopen_check"),
            timeout=1,
        )
    finally:
        stopped = await asyncio.wait_for(scheduler.stop(), timeout=1)

    assert started["running"] is True
    assert summary["event"] == "preopen_check_ok"
    assert scheduler.status()["last_preopen_check"] == summary
    assert stopped["running"] is False
    assert [call["event"] for call in notifier.calls if "event" in call] == [
        "market_ops_started",
        "preopen_check_ok",
        "market_ops_stopped",
    ]


@pytest.mark.asyncio
async def test_scheduler_prevents_overlapping_jobs() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingOps:
        async def preopen_check(self) -> dict[str, object]:
            entered.set()
            await release.wait()
            return {"ok": True, "event": "preopen_check_ok"}

    scheduler = MarketOpsScheduler(
        settings=ops_settings(),
        orchestrator=BlockingOps(),  # type: ignore[arg-type]
        now_provider=lambda: NOW,
    )
    task = asyncio.create_task(scheduler.run_job("preopen_check"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(MarketOpsJobBusyError):
            await asyncio.wait_for(scheduler.run_job("preopen_check"), timeout=1)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_scheduler_runs_due_job_once_and_survives_failed_job() -> None:
    calls: list[str] = []

    class ScheduledOps:
        async def preopen_check(self) -> dict[str, object]:
            calls.append("preopen")
            raise RuntimeError("failed")

        async def start_stream_if_ready(self) -> dict[str, object]:
            calls.append("stream_start")
            return {"ok": True, "event": "stream_started"}

    current = datetime(2026, 6, 11, 3, 25, tzinfo=timezone.utc)
    scheduler = MarketOpsScheduler(
        settings=ops_settings(),
        orchestrator=ScheduledOps(),  # type: ignore[arg-type]
        now_provider=lambda: current,
    )

    await asyncio.wait_for(scheduler._run_due_job(), timeout=1)
    await asyncio.wait_for(scheduler._run_due_job(), timeout=1)
    current = datetime(2026, 6, 11, 3, 38, tzinfo=timezone.utc)
    await asyncio.wait_for(scheduler._run_due_job(), timeout=1)

    assert calls == ["preopen", "stream_start"]
    assert scheduler.status()["last_error"] is None


@pytest.mark.asyncio
async def test_missing_login_arms_recovery_and_sends_one_link_per_episode() -> None:
    class MissingLoginOps:
        def __init__(self) -> None:
            self.link_calls = 0

        async def start_stream_if_ready(self) -> dict[str, object]:
            return {
                "ok": False,
                "event": "stream_start_skipped",
                "details": {"recommended_action": "login_kite"},
            }

        async def send_kite_login_link(self) -> bool:
            self.link_calls += 1
            return True

    ops = MissingLoginOps()
    scheduler = MarketOpsScheduler(
        settings=ops_settings(market_ops_login_recovery_enabled=True),
        orchestrator=ops,  # type: ignore[arg-type]
        now_provider=lambda: datetime(2026, 6, 11, 3, 30, tzinfo=timezone.utc),
    )

    await scheduler.run_job("stream_start")
    await scheduler.run_job("stream_start")

    status = scheduler.status()
    assert status["waiting_for_kite_login"] is True
    assert status["pending_action"] == "stream_start"
    assert ops.link_calls == 1


@pytest.mark.asyncio
async def test_recovery_starts_then_verifies_stream_inside_window() -> None:
    current = datetime(2026, 6, 11, 3, 30, tzinfo=timezone.utc)

    class RecoveringOps:
        def __init__(self) -> None:
            self.start_calls = 0
            self.verify_calls = 0

        async def start_stream_if_ready(self) -> dict[str, object]:
            self.start_calls += 1
            if self.start_calls == 1:
                return {
                    "ok": False,
                    "event": "stream_start_skipped",
                    "details": {"recommended_action": "login_kite"},
                }
            return {"ok": True, "event": "stream_started", "details": {}}

        async def verify_stream(self) -> dict[str, object]:
            self.verify_calls += 1
            return {"ok": True, "event": "stream_verify_ok", "details": {}}

        async def send_kite_login_link(self) -> bool:
            return True

    ops = RecoveringOps()
    scheduler = MarketOpsScheduler(
        settings=ops_settings(
            market_ops_login_recovery_enabled=True,
            market_ops_login_recovery_interval_seconds=30,
        ),
        orchestrator=ops,  # type: ignore[arg-type]
        now_provider=lambda: current,
    )

    await scheduler.run_job("stream_start")
    current = datetime(2026, 6, 11, 3, 30, 30, tzinfo=timezone.utc)
    await scheduler._run_recovery()
    assert scheduler.status()["pending_action"] == "stream_verify"
    current = datetime(2026, 6, 11, 3, 31, tzinfo=timezone.utc)
    await scheduler._run_recovery()

    assert ops.start_calls == 2
    assert ops.verify_calls == 1
    assert scheduler.status()["pending_action"] is None


@pytest.mark.asyncio
async def test_recovery_expires_and_never_runs_outside_window() -> None:
    current = datetime(2026, 6, 11, 3, 30, tzinfo=timezone.utc)

    class RecoveryOps:
        def __init__(self) -> None:
            self.start_calls = 0
            self.notifications: list[str] = []

        async def start_stream_if_ready(self) -> dict[str, object]:
            self.start_calls += 1
            return {
                "ok": False,
                "event": "stream_start_skipped",
                "details": {"recommended_action": "login_kite"},
            }

        async def send_kite_login_link(self) -> bool:
            return True

        async def notify_scheduler_event(self, **payload: object) -> None:
            self.notifications.append(str(payload["event"]))

    ops = RecoveryOps()
    scheduler = MarketOpsScheduler(
        settings=ops_settings(market_ops_login_recovery_enabled=True),
        orchestrator=ops,  # type: ignore[arg-type]
        now_provider=lambda: current,
    )
    await scheduler.run_job("stream_start")
    current = datetime(2026, 6, 11, 3, 56, tzinfo=timezone.utc)
    await scheduler._run_recovery()
    await scheduler._run_recovery()

    assert ops.start_calls == 1
    assert ops.notifications == ["kite_login_recovery_expired"]
    assert scheduler.status()["pending_action"] is None


@pytest.mark.asyncio
async def test_late_start_recovery_and_concurrent_start_use_one_loop() -> None:
    current = datetime(2026, 6, 11, 3, 40, tzinfo=timezone.utc)
    notifier = FakeNotifier()
    scheduler = MarketOpsScheduler(
        settings=ops_settings(market_ops_login_recovery_enabled=True),
        orchestrator=orchestrator(notifier=notifier),
        now_provider=lambda: current,
        poll_seconds=3600,
    )

    try:
        first, second = await asyncio.gather(scheduler.start(), scheduler.start())
    finally:
        await scheduler.stop()

    assert first["running"] is True
    assert second["running"] is True
    assert first["pending_action"] == "stream_start"
    assert [call["event"] for call in notifier.calls].count("market_ops_started") == 1


@pytest.mark.asyncio
async def test_app_lifespan_autostarts_only_when_both_flags_enabled(monkeypatch) -> None:
    class LifespanScheduler:
        def __init__(self) -> None:
            self.starts = 0
            self.stops = 0

        async def start(self) -> dict[str, object]:
            self.starts += 1
            return {}

        async def stop(self) -> dict[str, object]:
            self.stops += 1
            return {}

    scheduler = LifespanScheduler()

    async def provider() -> LifespanScheduler:
        return scheduler

    monkeypatch.setattr(dependencies, "get_market_ops_scheduler", provider)
    monkeypatch.setattr(dependencies.settings, "market_ops_autostart_enabled", False)
    monkeypatch.setattr(dependencies.settings, "market_ops_automation_enabled", True)
    async with app_lifespan(app):
        pass
    assert scheduler.starts == 0

    monkeypatch.setattr(dependencies.settings, "market_ops_autostart_enabled", True)
    async with app_lifespan(app):
        pass
    assert scheduler.starts == 1
    assert scheduler.stops == 1


def test_market_ops_routes_require_token_and_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteScheduler:
        def status(self) -> dict[str, object]:
            return {"enabled": False, "running": False}

        async def start(self) -> dict[str, object]:
            return {"enabled": True, "running": True}

        async def stop(self) -> dict[str, object]:
            return {"enabled": True, "running": False}

        async def run_job(self, name: str) -> dict[str, object]:
            return {"ok": True, "event": name}

    class RouteOps:
        async def test_notification(self) -> dict[str, object]:
            return {"ok": True, "event": "market_ops_test_notification"}

    app.dependency_overrides[get_market_ops_scheduler] = lambda: RouteScheduler()
    app.dependency_overrides[get_market_ops_orchestrator] = lambda: RouteOps()
    routes = [
        "/api/v1/ops/market-ops/run-preopen-check",
        "/api/v1/ops/market-ops/run-start-stream",
        "/api/v1/ops/market-ops/run-verify-stream",
        "/api/v1/ops/market-ops/run-universe-selection",
        "/api/v1/ops/market-ops/run-scanner-batch",
        "/api/v1/ops/market-ops/run-stop-stream",
        "/api/v1/ops/market-ops/test-notification",
    ]
    try:
        client = TestClient(app)
        assert client.get("/api/v1/ops/market-ops/status").status_code == 401
        started = client.post(
            "/api/v1/ops/market-ops/start",
            headers={"X-Operator-Token": "operator-secret"},
        )
        stopped = client.post(
            "/api/v1/ops/market-ops/stop",
            headers={"X-Operator-Token": "operator-secret"},
        )
        assert started.json()["running"] is True
        assert stopped.json()["running"] is False
        for route in routes:
            response = client.post(route, headers={"X-Operator-Token": "operator-secret"})
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_market_ops_route_start_then_stop_cancels_real_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")
    scheduler = MarketOpsScheduler(
        settings=ops_settings(),
        orchestrator=orchestrator(),
        now_provider=lambda: datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc),
        poll_seconds=3600,
    )
    app.dependency_overrides[get_market_ops_scheduler] = lambda: scheduler
    try:
        with TestClient(app) as client:
            started = client.post(
                "/api/v1/ops/market-ops/start",
                headers={"X-Operator-Token": "operator-secret"},
            )
            stopped = client.post(
                "/api/v1/ops/market-ops/stop",
                headers={"X-Operator-Token": "operator-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert started.status_code == 200
    assert started.json()["running"] is True
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False
    assert scheduler.status()["running"] is False


def test_market_ops_defaults_and_safety_boundaries() -> None:
    settings = Settings()
    compose = Path("infra/gcp/docker-compose.prod.yml").read_text(encoding="utf-8")
    sources = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (
            Path("backend/app/ops/notifier.py"),
            Path("backend/app/ops/market_ops.py"),
            Path("backend/app/ops/market_ops_scheduler.py"),
        )
    )

    assert settings.market_ops_automation_enabled is False
    assert settings.market_ops_notify_enabled is False
    assert settings.market_ops_notify_provider == "none"
    assert settings.market_ops_telegram_bot_token == ""
    assert settings.market_ops_telegram_chat_id == ""
    assert settings.market_ops_send_kite_login_link is False
    assert settings.market_ops_login_recovery_enabled is False
    assert settings.market_ops_autostart_enabled is False
    assert settings.paper_enabled is False
    assert settings.paper_mode == "OFF"
    assert 'TRADING_MODE: "OFF"' in compose
    assert 'LIVE_ARMED: "false"' in compose
    assert "paper.replay" not in sources
    assert "paper.run" not in sources
    assert "place_order" not in sources
    assert "openai" not in sources
    assert "kronos" not in sources
    assert " mcp" not in sources
    assert "yfinance" not in sources
    assert "beautifulsoup" not in sources
    assert "newspaper" not in sources
    assert "market_data_watchlist =" not in sources

    status = MarketOpsScheduler(
        settings=ops_settings(
            market_ops_telegram_bot_token="fake-token",
            market_ops_telegram_chat_id="123",
        ),
        orchestrator=orchestrator(),
        now_provider=lambda: NOW,
    ).status()
    assert "fake-token" not in str(status)
    assert "123" not in str(status)


def _universe_run() -> UniverseSelectionRun:
    return UniverseSelectionRun(
        run_id="run-1",
        started_at=NOW,
        finished_at=NOW,
        enabled=True,
        timeframe="1minute",
        pool_count=1,
        scored_count=1,
        selected_count=1,
        selected_symbols=["NSE:SBIN"],
        ranked_symbols=[],
        excluded_symbols=[],
        errors=[],
        warnings=[],
        config_snapshot={},
    )
