from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import get_decision_service
from app.api.dependencies import get_decision_automation_service
from app.core.config import Settings
from app.decision.exceptions import (
    DecisionAdapterError,
    DecisionConfigError,
    DecisionDisabledError,
    DecisionSignalIneligibleError,
    DecisionSignalNotFoundError,
)
from app.decision.fake_adapter import FakeDecisionAdapter
from app.decision.openai_adapter import OpenAIDecisionAdapter
from app.decision.repository import InMemoryDecisionRepository
from app.decision.schemas import DecisionOutput, DecisionSignal
from app.decision.service import DecisionService
from app.main import app
from app.scanners.schemas import CANDIDATE, REJECTED_SIGNAL


def decision_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "openai_decision_enabled": True,
        "openai_decision_adapter": "fake",
        "openai_decision_prompt_version": "p07_v1",
        "openai_decision_min_confidence": 0.60,
        "openai_decision_store": False,
        "openai_api_key": "",
        "openai_model": "",
        "paper_enabled": False,
        "paper_mode": "OFF",
    }
    values.update(overrides)
    return Settings(**values)


def candidate(*, status: str = CANDIDATE, features: dict[str, object] | None = None) -> DecisionSignal:
    return DecisionSignal(
        id=15,
        signal_key="replay:NSE:SBIN:opening_range_breakout_long",
        symbol="NSE:SBIN",
        strategy_name="opening_range_breakout_long",
        strategy_version="p05_v1",
        signal_status=status,
        signal_time=datetime(2026, 6, 9, 5, 29, tzinfo=timezone.utc),
        features={
            "indicator_values": {
                "ema_9": "100",
                "ema_20": "99",
                "atr_14": "1.2",
                "spread_pct": None,
                "unknown_secretish_context": "excluded",
            },
            "data_quality": {
                "history_complete": True,
                "quote_fresh": False,
                "spread_available": False,
            },
            "future_live_qualification": {
                "future_live_qualified": False,
                "warnings": ["spread_validation_missing"],
            },
            "raw_env": {"OPENAI_API_KEY": "must-not-pass"},
        }
        if features is None
        else features,
    )


def output(verdict: str = "ELIGIBLE", **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "verdict": verdict,
        "strategy_template": "opening_range_breakout_long",
        "confidence": 0.8,
        "reasons": ["technical_context_supported"],
        "warnings": [],
        "recommended_stop_method": "breakout_failure_or_atr",
        "recommended_target_r_multiple": 1.5,
        "data_sufficiency": "SUFFICIENT",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["ELIGIBLE", "WATCH", "REJECT"])
async def test_fake_adapter_persists_verdict_without_paper_side_effects(verdict: str) -> None:
    repo = InMemoryDecisionRepository(signals=[candidate()])
    service = DecisionService(
        settings=decision_settings(
            openai_decision_evaluation_mode="HISTORICAL_REPLAY"
        ),
        repository=repo,
        adapter=FakeDecisionAdapter(output(verdict)),
    )

    result = await service.evaluate(signal_id=15)

    assert result.verdict == verdict
    assert len(repo.model_runs) == 1
    assert len(repo.recommendations) == 1
    assert not hasattr(repo, "orders")
    assert not hasattr(repo, "trades")
    stored_input = repo.model_runs[0]["input_payload"]
    assert "raw_env" not in str(stored_input)
    assert "unknown_secretish_context" not in str(stored_input)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_output", "error_code"),
    [
        ("not-json", "malformed_output"),
        ({**output(), "quantity": 10}, "prohibited_output_field"),
        ({**output(), "broker_order_payload": {"side": "BUY"}}, "prohibited_output_field"),
        ({**output(), "risk_override": {"max_loss": 999}}, "prohibited_output_field"),
        ({**output(), "reasons": ["Company earnings are strong"]}, "external_fact_claim"),
        (output(confidence=0.2), "eligible_confidence_below_minimum"),
        (output(strategy_template="unknown_strategy"), "strategy_not_allowlisted"),
    ],
)
async def test_unsafe_outputs_become_audited_reject(
    raw_output: object,
    error_code: str,
) -> None:
    repo = InMemoryDecisionRepository(signals=[candidate()])
    service = DecisionService(
        settings=decision_settings(),
        repository=repo,
        adapter=FakeDecisionAdapter(raw_output),
    )

    result = await service.evaluate(signal_id=15)

    assert result.verdict == "REJECT"
    assert result.status == "FAILED"
    assert result.error_code == error_code
    assert repo.model_runs[0]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_missing_features_become_failed_run_and_reject() -> None:
    repo = InMemoryDecisionRepository(signals=[candidate(features={})])
    service = DecisionService(
        settings=decision_settings(),
        repository=repo,
        adapter=FakeDecisionAdapter(),
    )

    result = await service.evaluate(signal_id=15)

    assert result.verdict == "REJECT"
    assert result.error_code == "signal_features_missing"
    assert len(repo.model_runs) == 1


@pytest.mark.asyncio
async def test_openai_no_key_and_no_model_are_safe_rejections() -> None:
    for settings, expected in (
        (
            decision_settings(openai_decision_adapter="openai", openai_model="gpt-test"),
            "openai_api_key_missing",
        ),
        (
            decision_settings(openai_decision_adapter="openai", openai_api_key="test-key"),
            "openai_model_missing",
        ),
    ):
        repo = InMemoryDecisionRepository(signals=[candidate()])
        service = DecisionService(
            settings=settings,
            repository=repo,
            adapter=OpenAIDecisionAdapter(settings=settings),
        )
        result = await service.evaluate(signal_id=15)
        assert result.verdict == "REJECT"
        assert result.error_code == expected


@pytest.mark.asyncio
async def test_timeout_becomes_failed_run_and_safe_reject() -> None:
    class TimeoutAdapter:
        async def evaluate(self, _decision_input: object) -> object:
            raise DecisionAdapterError("openai_timeout")

    repo = InMemoryDecisionRepository(signals=[candidate()])
    result = await DecisionService(
        settings=decision_settings(),
        repository=repo,
        adapter=TimeoutAdapter(),  # type: ignore[arg-type]
    ).evaluate(signal_id=15)

    assert result.verdict == "REJECT"
    assert result.status == "FAILED"
    assert result.error_code == "openai_timeout"


@pytest.mark.asyncio
async def test_openai_request_has_no_tools_and_store_false() -> None:
    calls: list[dict[str, object]] = []

    class FakeResponses:
        async def parse(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(
                id="resp-1",
                status="completed",
                output_parsed=DecisionOutput.model_validate(output("WATCH")),
            )

    settings = decision_settings(
        openai_decision_adapter="openai",
        openai_api_key="test-key",
        openai_model="gpt-test",
        openai_decision_store=False,
    )
    adapter = OpenAIDecisionAdapter(settings=settings, responses_client=FakeResponses())

    await adapter.evaluate(
        DecisionService(
            settings=settings,
            repository=InMemoryDecisionRepository(),
            adapter=adapter,
        )._build_input(candidate())
    )

    request_payload = calls[0]
    assert request_payload["store"] is False
    assert request_payload["tool_choice"] == "none"
    assert "tools" not in request_payload
    serialized = str(request_payload).lower()
    assert "web_search" not in serialized
    assert "file_search" not in serialized
    assert "computer_use" not in serialized
    assert "function" not in serialized


@pytest.mark.asyncio
async def test_idempotency_and_force() -> None:
    repo = InMemoryDecisionRepository(signals=[candidate()])
    adapter = FakeDecisionAdapter(output())
    service = DecisionService(settings=decision_settings(), repository=repo, adapter=adapter)

    first = await service.evaluate(signal_id=15)
    second = await service.evaluate(signal_id=15)
    forced = await service.evaluate(signal_id=15, force=True)

    assert first.recommendation_id == second.recommendation_id
    assert second.existing is True
    assert forced.recommendation_id != first.recommendation_id
    assert len(repo.model_runs) == 2
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_verdict", "expected_error"),
    [
        ("HISTORICAL_REPLAY", "ELIGIBLE", None),
        ("LIVE_SHADOW", "WATCH", None),
        ("FUTURE_LIVE_ELIGIBILITY", "REJECT", "future_live_context_incomplete"),
    ],
)
async def test_evaluation_modes_normalize_incomplete_live_context(
    mode: str,
    expected_verdict: str,
    expected_error: str | None,
) -> None:
    raw = output(
        "ELIGIBLE",
        reasons=["model_explanation_preserved"],
    )
    repository = InMemoryDecisionRepository(signals=[candidate()])
    adapter = FakeDecisionAdapter(raw)
    result = await DecisionService(
        settings=decision_settings(openai_decision_evaluation_mode=mode),
        repository=repository,
        adapter=adapter,
    ).evaluate(signal_id=15)

    assert adapter.calls[0].evaluation_mode.value == mode
    assert result.verdict == expected_verdict
    assert result.error_code == expected_error
    assert repository.model_runs[0]["output_payload"]["verdict"] == "ELIGIBLE"  # type: ignore[index]
    assert repository.model_runs[0]["output_payload"]["reasons"] == [  # type: ignore[index]
        "model_explanation_preserved"
    ]
    if mode == "LIVE_SHADOW":
        assert "quote_fresh_missing" in result.warnings
        assert result.reasons == ["model_explanation_preserved"]


@pytest.mark.asyncio
async def test_raw_insufficient_explanation_is_preserved_but_recommendation_is_safe() -> None:
    repository = InMemoryDecisionRepository(signals=[candidate()])
    result = await DecisionService(
        settings=decision_settings(
            openai_decision_evaluation_mode="HISTORICAL_REPLAY"
        ),
        repository=repository,
        adapter=FakeDecisionAdapter(
            output(
                "WATCH",
                reasons=["original_missing_context_explanation"],
                data_sufficiency="INSUFFICIENT",
            )
        ),
    ).evaluate(signal_id=15)

    assert result.verdict == "REJECT"
    assert result.reasons == ["data_insufficient"]
    assert repository.model_runs[0]["output_payload"]["reasons"] == [  # type: ignore[index]
        "original_missing_context_explanation"
    ]


@pytest.mark.asyncio
async def test_prohibited_raw_fields_are_not_persisted() -> None:
    repository = InMemoryDecisionRepository(signals=[candidate()])
    await DecisionService(
        settings=decision_settings(),
        repository=repository,
        adapter=FakeDecisionAdapter(
            {
                **output(),
                "quantity": 10,
                "nested": {"api_key": "secret-value", "safe": "kept"},
            }
        ),
    ).evaluate(signal_id=15)

    raw = repository.model_runs[0]["output_payload"]
    assert "quantity" not in str(raw).lower()
    assert "api_key" not in str(raw).lower()
    assert "secret-value" not in str(raw)
    assert "kept" in str(raw)


@pytest.mark.asyncio
async def test_configured_secret_value_becomes_safe_reject_and_is_redacted() -> None:
    repository = InMemoryDecisionRepository(signals=[candidate()])
    result = await DecisionService(
        settings=decision_settings(openai_api_key="configured-secret-value"),
        repository=repository,
        adapter=FakeDecisionAdapter(
            output(reasons=["configured-secret-value"])
        ),
    ).evaluate(signal_id=15)

    assert result.verdict == "REJECT"
    assert result.error_code == "prohibited_output_value"
    assert "configured-secret-value" not in str(repository.model_runs[0]["output_payload"])


@pytest.mark.asyncio
async def test_invalid_evaluation_mode_is_rejected_before_adapter_call() -> None:
    adapter = FakeDecisionAdapter()
    service = DecisionService(
        settings=decision_settings(openai_decision_evaluation_mode="UNSAFE"),
        repository=InMemoryDecisionRepository(signals=[candidate()]),
        adapter=adapter,
    )

    with pytest.raises(DecisionConfigError):
        await service.evaluate(signal_id=15)
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_disabled_missing_and_non_candidate_fail_before_adapter() -> None:
    adapter = FakeDecisionAdapter()
    with pytest.raises(DecisionDisabledError):
        await DecisionService(
            settings=decision_settings(openai_decision_enabled=False),
            repository=InMemoryDecisionRepository(signals=[candidate()]),
            adapter=adapter,
        ).evaluate(signal_id=15)
    with pytest.raises(DecisionSignalNotFoundError):
        await DecisionService(
            settings=decision_settings(),
            repository=InMemoryDecisionRepository(),
            adapter=adapter,
        ).evaluate(signal_id=15)
    with pytest.raises(DecisionSignalIneligibleError):
        await DecisionService(
            settings=decision_settings(),
            repository=InMemoryDecisionRepository(
                signals=[candidate(status=REJECTED_SIGNAL)]
            ),
            adapter=adapter,
        ).evaluate(signal_id=15)
    assert adapter.calls == []


def test_decision_routes_require_operator_and_map_errors(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def status(self) -> dict[str, object]:
            return {"enabled": False}

        async def evaluate(self, *, signal_id: int, force: bool) -> object:
            raise DecisionSignalNotFoundError("Signal not found.")

        async def recommendations(self, *, limit: int) -> list[dict[str, object]]:
            return []

    app.dependency_overrides[get_decision_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        assert client.get("/api/v1/decision/status").status_code == 401
        status_response = client.get(
            "/api/v1/decision/status",
            headers={"X-Operator-Token": "operator-secret"},
        )
        missing_response = client.post(
            "/api/v1/decision/evaluate?signal_id=999",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert missing_response.status_code == 404


def test_decision_route_refuses_disabled_evaluation(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def evaluate(self, *, signal_id: int, force: bool) -> object:
            raise DecisionDisabledError("OpenAI decision evaluation is disabled.")

    app.dependency_overrides[get_decision_service] = lambda: RouteService()
    try:
        response = TestClient(app).post(
            "/api/v1/decision/evaluate?signal_id=15",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_decision_auto_routes_are_operator_protected(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteAutomation:
        def status(self) -> dict[str, object]:
            return {"enabled": False, "last_summary": None}

        async def evaluate_latest(self, *, limit: int) -> dict[str, object]:
            return {"attempted": limit, "created": 0}

    app.dependency_overrides[get_decision_automation_service] = lambda: RouteAutomation()
    try:
        client = TestClient(app)
        denied = client.get("/api/v1/decision/auto-status")
        status_response = client.get(
            "/api/v1/decision/auto-status",
            headers={"X-Operator-Token": "operator-secret"},
        )
        latest_response = client.post(
            "/api/v1/decision/evaluate-latest?limit=3",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 401
    assert status_response.json()["enabled"] is False
    assert latest_response.json()["attempted"] == 3


def test_decision_defaults_and_safety_boundaries() -> None:
    settings = Settings()
    compose = Path("infra/gcp/docker-compose.prod.yml").read_text(encoding="utf-8")
    sources = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in Path("backend/app/decision").glob("*.py")
    )

    assert settings.openai_decision_enabled is False
    assert settings.openai_decision_adapter == "fake"
    assert settings.openai_decision_store is False
    assert settings.openai_decision_evaluation_mode == "LIVE_SHADOW"
    assert settings.market_ops_decision_auto_evaluate_enabled is False
    assert 'TRADING_MODE: "OFF"' in compose
    assert 'LIVE_ARMED: "false"' in compose
    assert "place_order" not in sources
    assert "modify_order" not in sources
    assert "cancel_order" not in sources
    assert "kiteticker" not in sources
    assert "kronos" not in sources
    assert " mcp" not in sources
    assert "paper.replay" not in sources
