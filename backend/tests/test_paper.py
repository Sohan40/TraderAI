from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analysis.schemas import CompletedBar
from app.api import dependencies
from app.api.dependencies import get_paper_service
from app.core.config import Settings
from app.main import app
from app.paper.exceptions import (
    LiveModeNotImplementedError,
    PaperDisabledError,
    PaperModeDisabledError,
)
from app.paper.repository import InMemoryPaperRepository
from app.paper.schemas import PaperExitReason, PaperSignal
from app.paper.service import PaperService
from app.scanners.schemas import CANDIDATE, LONG, REJECTED_SIGNAL


def test_paper_defaults_are_disabled() -> None:
    settings = Settings()

    assert settings.paper_enabled is False
    assert settings.paper_mode == "OFF"
    assert settings.paper_max_trades_per_day == 3
    assert settings.paper_default_quantity == 1
    assert settings.paper_entry_buffer_pct == 0
    assert settings.paper_stop_pct == 0.50
    assert settings.paper_target_r_multiple == 2.0
    assert settings.paper_force_flat_time_ist == "15:10"
    assert settings.paper_estimated_cost_per_trade == 0


@pytest.mark.asyncio
async def test_paper_disabled_flag_refuses_replay_without_orders_or_fills() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(paper_enabled=False), repository=repo)

    with pytest.raises(PaperDisabledError):
        await service.run_replay(symbol="NSE:SBIN")

    assert repo.orders == []
    assert repo.trades == []


@pytest.mark.asyncio
async def test_off_mode_cannot_create_paper_orders_or_fills() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(paper_mode="OFF"), repository=repo)

    with pytest.raises(PaperModeDisabledError):
        await service.run_replay(symbol="NSE:SBIN")

    assert repo.orders == []
    assert repo.trades == []


@pytest.mark.asyncio
async def test_shadow_mode_cannot_create_paper_orders_or_fills() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(paper_mode="SHADOW"), repository=repo)

    with pytest.raises(PaperModeDisabledError):
        await service.run_replay(symbol="NSE:SBIN")

    assert repo.orders == []
    assert repo.trades == []


@pytest.mark.asyncio
async def test_live_mode_raises_disabled_not_implemented() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(paper_mode="LIVE"), repository=repo)

    with pytest.raises(LiveModeNotImplementedError):
        await service.run_replay(symbol="NSE:SBIN")

    assert repo.orders == []
    assert repo.trades == []


@pytest.mark.asyncio
async def test_paper_mode_creates_simulated_trade_from_valid_candidate() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")

    assert summary.signals_loaded == 1
    assert summary.trades_created == 1
    assert summary.outcomes[0].exit_reason == PaperExitReason.TARGET_HIT
    assert repo.orders[0]["simulated"] is True
    assert repo.trades[0]["simulated"] is True
    assert repo.journal[0]["simulated"] is True


@pytest.mark.asyncio
async def test_limit_entry_fill_path() -> None:
    repo = _repo_with(_candidate(), _time_exit_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.entry_order_status == "PAPER_ENTRY_FILLED"
    assert outcome.entry_fill_status == "FILLED"
    assert outcome.entry_fill_price == Decimal("100.000000")


@pytest.mark.asyncio
async def test_limit_no_fill_path() -> None:
    repo = _repo_with(_candidate(), _no_fill_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.NO_FILL
    assert outcome.entry_order_status == "PAPER_ENTRY_NO_FILL"
    assert outcome.entry_fill_time is None
    assert summary.trades_created == 0
    assert summary.no_fill_outcomes == 1
    assert len(repo.orders) == 1
    assert repo.orders[0]["status"] == "PAPER_ENTRY_NO_FILL"
    assert repo.trades == []
    assert repo.journal[0]["exit_reason"] == "NO_FILL"


@pytest.mark.asyncio
async def test_stop_hit_path() -> None:
    repo = _repo_with(_candidate(), _stop_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.STOP_HIT
    assert outcome.exit_price == Decimal("99.500000")
    assert outcome.gross_pnl == Decimal("-0.500000")


@pytest.mark.asyncio
async def test_target_hit_path() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.TARGET_HIT
    assert outcome.exit_price == Decimal("101.000000")
    assert outcome.gross_pnl == Decimal("1.000000")


@pytest.mark.asyncio
async def test_same_candle_stop_and_target_uses_stop_first() -> None:
    repo = _repo_with(_candidate(), _same_candle_stop_target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.STOP_HIT
    assert outcome.exit_price == Decimal("99.500000")


@pytest.mark.asyncio
async def test_time_exit_path() -> None:
    repo = _repo_with(_candidate(), _time_exit_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.TIME_EXIT
    assert outcome.exit_price == Decimal("100.250000")


@pytest.mark.asyncio
async def test_force_flat_path() -> None:
    repo = _repo_with(_candidate(), _force_flat_bars())
    service = PaperService(
        settings=_settings(paper_force_flat_time_ist="09:18"),
        repository=repo,
    )

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.FORCE_FLAT
    assert outcome.exit_price == Decimal("100.300000")


@pytest.mark.asyncio
async def test_duplicate_candidate_cannot_open_duplicate_paper_trade() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    first = await service.run_replay(symbol="NSE:SBIN")
    second = await service.run_replay(symbol="NSE:SBIN")

    assert first.trades_created == 1
    assert second.trades_created == 0
    assert second.outcomes[0].exit_reason == PaperExitReason.DUPLICATE_SIGNAL
    assert len(repo.trades) == 1


@pytest.mark.asyncio
async def test_no_fill_does_not_count_toward_daily_max_trades() -> None:
    no_fill_signal = _candidate(id=1, symbol="NSE:SBIN", instrument_id=1, key_suffix="no-fill")
    filled_signal = _candidate(
        id=2,
        symbol="NSE:NIFTYBEES",
        instrument_id=2,
        key_suffix="filled",
    )
    repo = InMemoryPaperRepository(
        signals=[no_fill_signal, filled_signal],
        candles_by_symbol={
            "NSE:SBIN": _no_fill_bars(symbol="NSE:SBIN", instrument_id=1),
            "NSE:NIFTYBEES": _target_bars(symbol="NSE:NIFTYBEES", instrument_id=2),
        },
    )
    service = PaperService(settings=_settings(paper_max_trades_per_day=1), repository=repo)

    summary = await service.run_replay()

    assert summary.signals_loaded == 2
    assert summary.entry_attempts == 2
    assert summary.no_fill_outcomes == 1
    assert summary.trades_created == 1
    assert len(repo.trades) == 1
    assert repo.trades[0]["signal_id"] == 2
    assert [outcome.exit_reason for outcome in summary.outcomes] == [
        PaperExitReason.NO_FILL,
        PaperExitReason.TARGET_HIT,
    ]


@pytest.mark.asyncio
async def test_pnl_and_estimated_cost_are_calculated() -> None:
    repo = _repo_with(_candidate(), _target_bars())
    service = PaperService(
        settings=_settings(paper_default_quantity=2, paper_estimated_cost_per_trade=0.25),
        repository=repo,
    )

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.gross_pnl == Decimal("2.000000")
    assert outcome.estimated_costs == Decimal("0.25")
    assert outcome.net_estimated_pnl == Decimal("1.750000")
    assert repo.trades[0]["net_pnl"] == Decimal("1.750000")


@pytest.mark.asyncio
async def test_rejected_signal_never_creates_paper_trade() -> None:
    signal = _candidate(status=REJECTED_SIGNAL, veto_reasons=["scanner_veto"])
    repo = _repo_with(signal, _target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")

    assert summary.signals_loaded == 0
    assert repo.orders == []
    assert repo.trades == []


@pytest.mark.asyncio
async def test_missing_signal_context_creates_clear_rejected_paper_outcome() -> None:
    signal = _candidate(features={})
    repo = _repo_with(signal, _target_bars())
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    outcome = summary.outcomes[0]

    assert outcome.exit_reason == PaperExitReason.INVALID_SIGNAL_CONTEXT
    assert outcome.rejection_reason == "missing_signal_features"
    assert repo.orders == []
    assert repo.trades == []
    assert repo.journal[0]["rejection_reason"] == "missing_signal_features"


@pytest.mark.asyncio
async def test_paper_report_and_trades_return_journal_fields() -> None:
    no_fill_signal = _candidate(id=1, symbol="NSE:SBIN", instrument_id=1, key_suffix="no-fill")
    filled_signal = _candidate(
        id=2,
        symbol="NSE:NIFTYBEES",
        instrument_id=2,
        key_suffix="filled",
    )
    repo = InMemoryPaperRepository(
        signals=[no_fill_signal, filled_signal],
        candles_by_symbol={
            "NSE:SBIN": _no_fill_bars(symbol="NSE:SBIN", instrument_id=1),
            "NSE:NIFTYBEES": _target_bars(symbol="NSE:NIFTYBEES", instrument_id=2),
        },
    )
    service = PaperService(settings=_settings(), repository=repo)
    await service.run_replay()

    report = await service.report()
    trades = await service.trades()

    assert report["paper_mode"] == "PAPER"
    assert report["paper_trade_outcomes"] == 1
    assert report["entry_attempt_outcomes"] == 2
    assert report["no_fill_outcomes"] == 1
    assert report["filled_paper_trade_outcomes"] == 1
    assert report["net_estimated_pnl"] == "1.000000"
    assert {trade["exit_reason"] for trade in trades} == {"NO_FILL", "TARGET_HIT"}
    filled = next(trade for trade in trades if trade["exit_reason"] == "TARGET_HIT")
    assert filled["entry_reference_price"] == "100.000000"


@pytest.mark.asyncio
async def test_paper_report_adds_read_only_decision_comparison_without_gating() -> None:
    repo = InMemoryPaperRepository(
        signals=[_candidate()],
        candles_by_symbol={"NSE:SBIN": _target_bars()},
        decisions_by_signal={
            1: {
                "recommendation_id": 7,
                "verdict": "REJECT",
                "confidence": 0.2,
                "warnings": ["historical_context"],
                "prompt_version": "p07_v1",
            }
        },
    )
    service = PaperService(settings=_settings(), repository=repo)

    summary = await service.run_replay(symbol="NSE:SBIN")
    report = await service.report()
    outcomes = await service.trades()

    assert summary.trades_created == 1
    assert report["model_decision_coverage"] == 1
    assert report["model_decision_verdict_counts"] == {"REJECT": 1}
    assert outcomes[0]["model_decision"]["verdict"] == "REJECT"  # type: ignore[index]


def test_paper_routes_require_operator_and_return_safe_status(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def status(self) -> dict[str, object]:
            return {"paper_enabled": False, "paper_mode": "OFF", "simulated_only": True}

    app.dependency_overrides[get_paper_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        missing = client.get("/api/v1/paper/status")
        ok = client.get("/api/v1/paper/status", headers={"X-Operator-Token": "operator-secret"})
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["simulated_only"] is True


def test_paper_route_refuses_disabled_replay(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def run_replay(self, **_kwargs: object) -> object:
            raise PaperDisabledError("disabled")

    app.dependency_overrides[get_paper_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/paper/run-replay?symbol=NSE:SBIN",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "paper disabled"


def test_paper_modules_do_not_import_kite_or_ai_modules() -> None:
    forbidden_case_sensitive = ("KiteConnect", "KiteTicker")
    forbidden_lower = (
        "place_order",
        "modify_order",
        "cancel_order",
        "holdings",
        "positions",
        "margins",
        "gtt",
        "openai",
        "langgraph",
        "kronos",
        "mcp",
    )
    for path in Path("backend/app/paper").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert not any(term in text for term in forbidden_case_sensitive), path
        assert not any(term in lowered for term in forbidden_lower), path


def test_production_compose_keeps_live_disabled_and_paper_defaults_off() -> None:
    compose = Path("infra/gcp/docker-compose.prod.yml").read_text(encoding="utf-8")

    assert 'TRADING_MODE: "OFF"' in compose
    assert 'LIVE_ARMED: "false"' in compose
    assert 'PAPER_ENABLED: "${PAPER_ENABLED:-false}"' in compose
    assert 'PAPER_MODE: "${PAPER_MODE:-OFF}"' in compose


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "paper_enabled": True,
        "paper_mode": "PAPER",
        "paper_max_trades_per_day": 3,
        "paper_default_quantity": 1,
        "paper_entry_buffer_pct": 0,
        "paper_stop_pct": 0.50,
        "paper_target_r_multiple": 2.0,
        "paper_force_flat_time_ist": "15:10",
        "paper_estimated_cost_per_trade": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _candidate(
    *,
    id: int = 1,
    instrument_id: int = 1,
    symbol: str = "NSE:SBIN",
    minute: int = 0,
    key_suffix: str = "NSE:SBIN",
    status: str = CANDIDATE,
    veto_reasons: list[str] | None = None,
    features: dict[str, object] | None = None,
) -> PaperSignal:
    vetoes = veto_reasons or []
    snapshot = {
        "signal_status": status,
        "veto_reasons": list(vetoes),
        "indicator_values": {"atr_14": "1.00"},
        "data_quality": {"history_complete": True},
    }
    return PaperSignal(
        id=id,
        instrument_id=instrument_id,
        signal_key=f"paper-test:{key_suffix}",
        symbol=symbol,
        strategy_name="opening_range_breakout_long",
        strategy_version="p05_v1",
        signal_status=status,
        signal_time=_dt(minute),
        direction=LONG,
        veto_reasons=vetoes,
        features=snapshot if features is None else features,
        replay_run_id="paper-test",
    )


def _repo_with(signal: PaperSignal, bars: list[CompletedBar]) -> InMemoryPaperRepository:
    return InMemoryPaperRepository(signals=[signal], candles_by_symbol={"NSE:SBIN": bars})


def _target_bars(
    *,
    symbol: str = "NSE:SBIN",
    instrument_id: int = 1,
) -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100"), symbol=symbol, instrument_id=instrument_id),
        _bar(
            1,
            close=Decimal("100.10"),
            high=Decimal("100.20"),
            low=Decimal("99.90"),
            symbol=symbol,
            instrument_id=instrument_id,
        ),
        _bar(
            2,
            close=Decimal("101.10"),
            high=Decimal("101.20"),
            low=Decimal("100.20"),
            symbol=symbol,
            instrument_id=instrument_id,
        ),
    ]


def _stop_bars() -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100")),
        _bar(1, close=Decimal("100.10"), high=Decimal("100.20"), low=Decimal("99.90")),
        _bar(2, close=Decimal("99.40"), high=Decimal("100.20"), low=Decimal("99.40")),
    ]


def _same_candle_stop_target_bars() -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100")),
        _bar(1, close=Decimal("100.10"), high=Decimal("100.20"), low=Decimal("99.90")),
        _bar(2, close=Decimal("100.00"), high=Decimal("101.20"), low=Decimal("99.40")),
    ]


def _time_exit_bars() -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100")),
        _bar(1, close=Decimal("100.10"), high=Decimal("100.20"), low=Decimal("99.90")),
        _bar(2, close=Decimal("100.25"), high=Decimal("100.30"), low=Decimal("99.80")),
    ]


def _force_flat_bars() -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100")),
        _bar(1, close=Decimal("100.10"), high=Decimal("100.20"), low=Decimal("99.90")),
        _bar(2, close=Decimal("100.20"), high=Decimal("100.30"), low=Decimal("99.80")),
        _bar(3, close=Decimal("100.30"), high=Decimal("100.40"), low=Decimal("99.80")),
    ]


def _no_fill_bars(
    *,
    symbol: str = "NSE:SBIN",
    instrument_id: int = 1,
) -> list[CompletedBar]:
    return [
        _bar(0, close=Decimal("100"), symbol=symbol, instrument_id=instrument_id),
        _bar(
            1,
            close=Decimal("100.50"),
            high=Decimal("101.00"),
            low=Decimal("100.10"),
            symbol=symbol,
            instrument_id=instrument_id,
        ),
        _bar(
            2,
            close=Decimal("100.80"),
            high=Decimal("101.20"),
            low=Decimal("100.20"),
            symbol=symbol,
            instrument_id=instrument_id,
        ),
    ]


def _bar(
    index: int,
    *,
    close: Decimal,
    high: Decimal | None = None,
    low: Decimal | None = None,
    symbol: str = "NSE:SBIN",
    instrument_id: int = 1,
) -> CompletedBar:
    return CompletedBar(
        instrument_id=instrument_id,
        symbol=symbol,
        timeframe="1minute",
        started_at=_dt(index),
        open_price=close,
        high_price=high or close + Decimal("0.50"),
        low_price=low or close - Decimal("0.50"),
        close_price=close,
        volume=100,
    )


def _dt(minutes: int) -> datetime:
    return datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc) + timedelta(minutes=minutes)
