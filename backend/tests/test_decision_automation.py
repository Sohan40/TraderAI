from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.decision.automation import DecisionAutomationService
from app.decision.exceptions import DecisionAdapterError, DecisionDisabledError
from app.decision.fake_adapter import FakeDecisionAdapter
from app.decision.repository import InMemoryDecisionRepository
from app.decision.schemas import DecisionSignal
from app.decision.service import DecisionService
from app.scanners.schemas import CANDIDATE, REJECTED_SIGNAL

NOW = datetime(2026, 6, 11, 5, 0, tzinfo=timezone.utc)


def settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "openai_decision_enabled": True,
        "openai_decision_adapter": "fake",
        "openai_decision_evaluation_mode": "HISTORICAL_REPLAY",
        "market_ops_decision_auto_evaluate_enabled": True,
        "market_ops_decision_auto_evaluate_max_signals": 5,
        "market_ops_decision_auto_evaluate_only_candidates": True,
        "market_ops_decision_notify_enabled": True,
        "market_ops_decision_notify_verdicts": "ELIGIBLE,WATCH,REJECT",
    }
    values.update(overrides)
    return Settings(**values)


def candidate(
    signal_id: int,
    *,
    status: str = CANDIDATE,
    created_at: datetime | None = None,
    symbol: str = "NSE:SBIN",
) -> DecisionSignal:
    return DecisionSignal(
        id=signal_id,
        signal_key=f"signal-{signal_id}",
        symbol=symbol,
        strategy_name="opening_range_breakout_long",
        strategy_version="p05_v1",
        signal_status=status,
        signal_time=NOW + timedelta(seconds=signal_id),
        created_at=created_at or NOW + timedelta(seconds=signal_id),
        features={
            "indicator_values": {"ema_9": "100", "ema_20": "99"},
            "data_quality": {"history_complete": True, "quote_fresh": False},
            "future_live_qualification": {
                "spread_required": True,
                "spread_validated": False,
            },
        },
    )


def decision_output(verdict: str = "WATCH") -> dict[str, object]:
    return {
        "verdict": verdict,
        "strategy_template": "opening_range_breakout_long",
        "confidence": 0.75,
        "reasons": ["reason-one", "reason-two", "reason-three"],
        "warnings": ["warning-one", "warning-two", "warning-three"],
        "recommended_stop_method": None,
        "recommended_target_r_multiple": None,
        "data_sufficiency": "SUFFICIENT",
    }


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def notify(self, **payload: object) -> object:
        self.calls.append(payload)
        return SimpleNamespace(ok=True, skipped=False)


def automation(
    *,
    configured: Settings,
    repository: InMemoryDecisionRepository,
    adapter: object,
    notifier: FakeNotifier,
) -> DecisionAutomationService:
    decision_service = DecisionService(
        settings=configured,
        repository=repository,
        adapter=adapter,  # type: ignore[arg-type]
    )
    return DecisionAutomationService(
        settings=configured,
        decision_service=decision_service,
        repository=repository,
        notifier=notifier,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "candidate_count", "dry_run", "reason"),
    [
        (
            {"market_ops_decision_auto_evaluate_enabled": False},
            1,
            False,
            "auto_evaluation_disabled",
        ),
        (
            {"openai_decision_enabled": False},
            1,
            False,
            "decision_service_disabled",
        ),
        ({}, 0, False, "no_candidates"),
        ({}, 1, True, "scanner_dry_run"),
        (
            {"market_ops_decision_auto_evaluate_only_candidates": False},
            1,
            False,
            "candidate_only_required",
        ),
    ],
)
async def test_auto_evaluation_skip_gates(
    overrides: dict[str, object],
    candidate_count: int,
    dry_run: bool,
    reason: str,
) -> None:
    adapter = FakeDecisionAdapter(decision_output())
    service = automation(
        configured=settings(**overrides),
        repository=InMemoryDecisionRepository(signals=[candidate(1)]),
        adapter=adapter,
        notifier=FakeNotifier(),
    )

    summary = await service.evaluate_scanner_batch(
        started_at=NOW,
        finished_at=NOW + timedelta(minutes=1),
        symbols=["NSE:SBIN"],
        dry_run=dry_run,
        candidate_count=candidate_count,
    )

    assert summary["skipped_reason"] == reason
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_auto_evaluation_is_bounded_oldest_first_and_candidate_only() -> None:
    adapter = FakeDecisionAdapter(decision_output())
    notifier = FakeNotifier()
    repository = InMemoryDecisionRepository(
        signals=[
            candidate(1),
            candidate(2),
            candidate(3),
            candidate(4, status=REJECTED_SIGNAL),
        ]
    )
    service = automation(
        configured=settings(market_ops_decision_auto_evaluate_max_signals=2),
        repository=repository,
        adapter=adapter,
        notifier=notifier,
    )

    summary = await service.evaluate_scanner_batch(
        started_at=NOW,
        finished_at=NOW + timedelta(minutes=1),
        symbols=["NSE:SBIN"],
        dry_run=False,
        candidate_count=3,
    )

    assert summary["attempted"] == 2
    assert summary["created"] == 2
    assert summary["truncated"] is True
    assert [item.signal_id for item in adapter.calls] == [1, 2]
    assert len(notifier.calls) == 2


@pytest.mark.asyncio
async def test_auto_evaluation_scopes_candidates_to_batch_window_and_symbols() -> None:
    adapter = FakeDecisionAdapter(decision_output())
    repository = InMemoryDecisionRepository(
        signals=[
            candidate(1),
            candidate(2, created_at=NOW - timedelta(minutes=1)),
            candidate(3, symbol="NSE:INFY"),
        ]
    )
    service = automation(
        configured=settings(),
        repository=repository,
        adapter=adapter,
        notifier=FakeNotifier(),
    )

    summary = await service.evaluate_scanner_batch(
        started_at=NOW,
        finished_at=NOW + timedelta(minutes=1),
        symbols=["NSE:SBIN"],
        dry_run=False,
        candidate_count=3,
    )

    assert summary["attempted"] == 1
    assert [item.signal_id for item in adapter.calls] == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "level", "event"),
    [
        ("ELIGIBLE", "warning", "decision_candidate_eligible"),
        ("WATCH", "info", "decision_candidate_watch"),
        ("REJECT", "info", "decision_candidate_rejected"),
    ],
)
async def test_new_decision_sends_bounded_verdict_notification(
    verdict: str,
    level: str,
    event: str,
) -> None:
    notifier = FakeNotifier()
    service = automation(
        configured=settings(),
        repository=InMemoryDecisionRepository(signals=[candidate(1)]),
        adapter=FakeDecisionAdapter(decision_output(verdict)),
        notifier=notifier,
    )

    summary = await service.evaluate_latest(limit=5)

    assert summary["notified"] == 1
    notification = notifier.calls[0]
    assert notification["level"] == level
    assert notification["event"] == event
    details = notification["details"]
    assert isinstance(details, dict)
    assert details["reasons"] == ["reason-one", "reason-two"]
    assert details["warnings"] == ["warning-one", "warning-two"]
    assert "payload" not in str(notification).lower()


@pytest.mark.asyncio
async def test_failed_decision_persists_safe_reject_and_warns() -> None:
    class FailingAdapter:
        async def evaluate(self, _input: object) -> object:
            raise DecisionAdapterError("openai_timeout")

    notifier = FakeNotifier()
    repository = InMemoryDecisionRepository(signals=[candidate(1)])
    service = automation(
        configured=settings(),
        repository=repository,
        adapter=FailingAdapter(),
        notifier=notifier,
    )

    summary = await service.evaluate_latest(limit=1)

    assert summary["created"] == 1
    assert summary["failed"] == 1
    assert repository.recommendations[0].verdict == "REJECT"
    assert notifier.calls[0]["level"] == "warning"
    assert notifier.calls[0]["event"] == "decision_auto_evaluation_failed"


@pytest.mark.asyncio
async def test_one_failed_decision_does_not_stop_later_candidates() -> None:
    class ScriptedAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def evaluate(self, _input: object) -> object:
            self.calls += 1
            if self.calls == 1:
                raise DecisionAdapterError("openai_timeout")
            return SimpleNamespace(
                output=decision_output("WATCH"),
                request_id="scripted",
                latency_ms=0,
            )

    repository = InMemoryDecisionRepository(signals=[candidate(1), candidate(2)])
    service = automation(
        configured=settings(),
        repository=repository,
        adapter=ScriptedAdapter(),
        notifier=FakeNotifier(),
    )

    summary = await service.evaluate_latest(limit=2)

    assert summary["attempted"] == 2
    assert summary["created"] == 2
    assert summary["failed"] == 1
    assert [item.verdict for item in repository.recommendations] == ["REJECT", "WATCH"]


@pytest.mark.asyncio
async def test_existing_recommendation_is_not_notified_again() -> None:
    notifier = FakeNotifier()
    adapter = FakeDecisionAdapter(decision_output())
    repository = InMemoryDecisionRepository(signals=[candidate(1)])
    service = automation(
        configured=settings(),
        repository=repository,
        adapter=adapter,
        notifier=notifier,
    )

    first = await service.evaluate_latest(limit=1)
    second = await service.evaluate_latest(limit=1)

    assert first["created"] == 1
    assert second["attempted"] == 0
    assert len(notifier.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_evaluation_is_idempotent() -> None:
    adapter = FakeDecisionAdapter(decision_output())
    repository = InMemoryDecisionRepository(signals=[candidate(1)])
    decision_service = DecisionService(
        settings=settings(),
        repository=repository,
        adapter=adapter,
    )

    first, second = await asyncio.gather(
        decision_service.evaluate(signal_id=1),
        decision_service.evaluate(signal_id=1),
    )

    assert first.recommendation_id == second.recommendation_id
    assert len(adapter.calls) == 1
    assert len(repository.recommendations) == 1


@pytest.mark.asyncio
async def test_manual_latest_requires_decision_enabled() -> None:
    service = automation(
        configured=settings(openai_decision_enabled=False),
        repository=InMemoryDecisionRepository(signals=[candidate(1)]),
        adapter=FakeDecisionAdapter(),
        notifier=FakeNotifier(),
    )

    with pytest.raises(DecisionDisabledError):
        await service.evaluate_latest(limit=1)


@pytest.mark.asyncio
async def test_manual_latest_does_not_require_auto_evaluation_enabled() -> None:
    adapter = FakeDecisionAdapter(decision_output())
    service = automation(
        configured=settings(market_ops_decision_auto_evaluate_enabled=False),
        repository=InMemoryDecisionRepository(signals=[candidate(1)]),
        adapter=adapter,
        notifier=FakeNotifier(),
    )

    summary = await service.evaluate_latest(limit=1)

    assert summary["created"] == 1
    assert len(adapter.calls) == 1
