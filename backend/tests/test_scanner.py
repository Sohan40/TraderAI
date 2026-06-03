from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.analysis.feature_builder import build_indicator_snapshot
from app.analysis.indicators import atr_wilder, candle_continuity_ok, ema, rsi_wilder, spread_pct, vwap
from app.analysis.schemas import CompletedBar, QuoteContext
from app.api import dependencies
from app.api.dependencies import get_scanner_service
from app.core.config import Settings
from app.main import app
from app.scanners.exceptions import ScannerDisabledError, ScannerInputError
from app.scanners.repository import InMemoryScannerRepository
from app.scanners.replay import _run as run_replay
from app.scanners.schemas import CANDIDATE, REJECTED_SIGNAL
from app.scanners.service import ScannerService, scanner_config_from_settings
from app.scanners.strategies import evaluate_strategy
from app.scanners.vetoes import (
    DATA_QUALITY_FAILURE,
    SPREAD_TOO_WIDE,
    SPREAD_UNAVAILABLE_WHEN_REQUIRED,
    STALE_QUOTE_OR_DATA,
)


def test_scanner_defaults_are_disabled() -> None:
    settings = Settings()

    assert settings.scanner_enabled is False
    assert settings.scanner_observation_mode == "SHADOW"


def test_ema_known_value_and_missing_history() -> None:
    assert ema([Decimal("1"), Decimal("2")], 3) is None
    assert ema([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")], 3) == Decimal("3.0000")


def test_rsi_known_value_and_missing_history() -> None:
    assert rsi_wilder([Decimal("1")] * 14, 14) is None
    closes = [Decimal(value) for value in ("1 2 3 4 5 6 7 8 9 10 11 12 13 14 15").split()]
    assert rsi_wilder(closes, 14) == Decimal("100")


def test_atr_known_value_and_missing_history() -> None:
    bars = _bars(count=14)
    assert atr_wilder(bars, 14) is None
    assert atr_wilder(_bars(count=15), 14) == Decimal("2.0000")


def test_vwap_and_spread_availability() -> None:
    bars = _bars(count=2, volume=100)

    assert vwap(bars) == Decimal("100.5000")
    assert vwap(_bars(count=2, volume=0)) is None
    assert spread_pct(None) is None
    assert spread_pct(QuoteContext(bid_price=Decimal("99"), ask_price=Decimal("101"))) == Decimal("2.0000")


def test_feature_builder_handles_opening_previous_day_volume_benchmark_and_spread() -> None:
    previous_day = _bars(count=5, start=datetime(2026, 6, 2, 3, 45, tzinfo=timezone.utc), price=90)
    current_day = _bars(count=51, start=datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc), price=100)
    benchmark = _bars(count=51, start=datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc), price=99)

    snapshot = build_indicator_snapshot(
        previous_day + current_day,
        benchmark_bars=benchmark,
        quote_context=QuoteContext(bid_price=Decimal("100"), ask_price=Decimal("100.10")),
    )

    assert snapshot.ema_9 is not None
    assert snapshot.opening_range_high is not None
    assert snapshot.previous_day_high == Decimal("92")
    assert snapshot.volume_ratio is not None
    assert snapshot.relative_index_move is not None
    assert snapshot.spread_pct == Decimal("0.1000")


def test_opening_range_breakout_candidate_only_when_conditions_pass() -> None:
    bars = _candidate_bars()
    config = scanner_config_from_settings(
        Settings(
            scanner_enabled=True,
            scanner_min_volume_ratio=1.5,
            scanner_require_spread_for_future_live=False,
        )
    )

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=bars,
        config=config,
    )

    assert evaluation.status == CANDIDATE
    assert evaluation.veto_reasons == []


def test_shadow_candidate_is_not_rejected_when_future_live_spread_is_missing() -> None:
    bars = _candidate_bars()
    config = scanner_config_from_settings(Settings(scanner_enabled=True))

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=bars,
        config=config,
        quote_context=None,
    )

    features = evaluation.snapshot.as_dict()
    data_quality = cast(dict[str, bool], features["data_quality"])
    qualification = cast(dict[str, object], features["future_live_qualification"])
    assert evaluation.status == CANDIDATE
    assert SPREAD_UNAVAILABLE_WHEN_REQUIRED not in evaluation.veto_reasons
    assert data_quality["spread_available"] is False
    assert qualification["eligible_strategy"] is True
    assert qualification["spread_required"] is True
    assert qualification["spread_validated"] is False
    assert qualification["future_live_qualified"] is False
    assert "spread_validation_missing" in cast(list[str], qualification["warnings"])


def test_eligible_strategy_with_acceptable_spread_can_mark_future_live_metadata() -> None:
    config = scanner_config_from_settings(Settings(scanner_enabled=True))

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=_candidate_bars(),
        config=config,
        quote_context=QuoteContext(bid_price=Decimal("100"), ask_price=Decimal("100.10")),
    )

    qualification = cast(
        dict[str, object],
        evaluation.snapshot.as_dict()["future_live_qualification"],
    )
    assert evaluation.status == CANDIDATE
    assert qualification["eligible_strategy"] is True
    assert qualification["spread_validated"] is True
    assert qualification["future_live_qualified"] is True


def test_future_live_eligibility_mode_rejects_missing_required_spread() -> None:
    config = scanner_config_from_settings(
        Settings(scanner_enabled=True, scanner_observation_mode="FUTURE_LIVE_ELIGIBILITY")
    )

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=_candidate_bars(),
        config=config,
        quote_context=None,
    )

    assert evaluation.status == REJECTED_SIGNAL
    assert SPREAD_UNAVAILABLE_WHEN_REQUIRED in evaluation.veto_reasons


def test_wide_supplied_spread_rejects_shadow_candidate() -> None:
    config = scanner_config_from_settings(Settings(scanner_enabled=True))

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=_candidate_bars(),
        config=config,
        quote_context=QuoteContext(bid_price=Decimal("100"), ask_price=Decimal("101")),
    )

    assert evaluation.status == REJECTED_SIGNAL
    assert SPREAD_TOO_WIDE in evaluation.veto_reasons


def test_vwap_pullback_candidate_only_when_conditions_pass() -> None:
    bars = _candidate_bars()
    bars[-2] = _bar(49, close=Decimal("99"), high=Decimal("100"), volume=100)
    bars[-1] = _bar(50, close=Decimal("102"), high=Decimal("103"), volume=220)
    config = scanner_config_from_settings(
        Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False)
    )

    evaluation = evaluate_strategy(
        strategy_name="vwap_pullback_continuation_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=bars,
        config=config,
    )

    assert evaluation.status == CANDIDATE


def test_non_eligible_vwap_candidate_is_never_future_live_qualified() -> None:
    bars = _candidate_bars()
    bars[-2] = _bar(49, close=Decimal("99"), high=Decimal("100"), volume=100)
    bars[-1] = _bar(50, close=Decimal("102"), high=Decimal("103"), volume=220)
    config = scanner_config_from_settings(Settings(scanner_enabled=True))

    evaluation = evaluate_strategy(
        strategy_name="vwap_pullback_continuation_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=bars,
        config=config,
    )

    qualification = cast(
        dict[str, object],
        evaluation.snapshot.as_dict()["future_live_qualification"],
    )
    assert evaluation.status == CANDIDATE
    assert qualification["eligible_strategy"] is False
    assert qualification["future_live_qualified"] is False


def test_hard_vetoes_create_rejected_signal_with_reason() -> None:
    config = scanner_config_from_settings(Settings(scanner_enabled=True))

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="BSE:SBIN",
        timeframe="1minute",
        bars=_bars(count=10),
        config=config,
    )

    assert evaluation.status == REJECTED_SIGNAL
    assert "unsupported_symbol" in evaluation.veto_reasons
    assert "missing_history" in evaluation.veto_reasons


@pytest.mark.asyncio
async def test_scanner_service_refuses_when_disabled_and_deduplicates_when_enabled() -> None:
    repository = InMemoryScannerRepository({"NSE:SBIN": _candidate_bars()})
    disabled = ScannerService(settings=Settings(scanner_enabled=False), repository=repository)

    with pytest.raises(ScannerDisabledError):
        await disabled.run_once(symbol="NSE:SBIN")

    enabled = ScannerService(
        settings=Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False),
        repository=repository,
        now_provider=lambda: _fresh_now(repository.bars_by_symbol["NSE:SBIN"]),
    )
    first = await enabled.run_once(symbol="NSE:SBIN")
    second = await enabled.run_once(symbol="NSE:SBIN")

    assert first.inserted == 2
    assert second.duplicates == 2


@pytest.mark.asyncio
async def test_scanner_service_refuses_unsupported_timeframe() -> None:
    service = ScannerService(
        settings=Settings(scanner_enabled=True),
        repository=InMemoryScannerRepository({"NSE:SBIN": _candidate_bars()}),
    )

    with pytest.raises(ScannerInputError):
        await service.run_once(symbol="NSE:SBIN", timeframe="5minute")


@pytest.mark.asyncio
async def test_live_scanner_run_persists_stale_data_veto() -> None:
    bars = _candidate_bars()
    repository = InMemoryScannerRepository({"NSE:SBIN": bars})
    service = ScannerService(
        settings=Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False),
        repository=repository,
        now_provider=lambda: bars[-1].started_at + timedelta(minutes=5),
    )

    result = await service.run_once(symbol="NSE:SBIN")

    assert result.rejected == 2
    assert result.veto_counts[STALE_QUOTE_OR_DATA] == 2
    signals = await service.list_signals()
    assert all(
        STALE_QUOTE_OR_DATA in cast(list[str], signal["veto_reasons"]) for signal in signals
    )


@pytest.mark.asyncio
async def test_replay_run_does_not_apply_wall_clock_staleness() -> None:
    bars = _candidate_bars()
    repository = InMemoryScannerRepository({"NSE:SBIN": bars})
    service = ScannerService(
        settings=Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False),
        repository=repository,
        now_provider=lambda: bars[-1].started_at + timedelta(days=10),
    )

    await service.run_once(symbol="NSE:SBIN", replay_run_id="replay_stale_wall_clock")

    signals = await service.list_signals()
    assert all(
        STALE_QUOTE_OR_DATA not in cast(list[str], signal["veto_reasons"]) for signal in signals
    )


@pytest.mark.asyncio
async def test_replay_identity_produces_deterministic_signals() -> None:
    repository = InMemoryScannerRepository({"NSE:SBIN": _candidate_bars()})
    service = ScannerService(
        settings=Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False),
        repository=repository,
        now_provider=lambda: datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc),
    )

    first = await service.run_once(symbol="NSE:SBIN", replay_run_id="replay_a")
    second = await service.run_once(symbol="NSE:SBIN", replay_run_id="replay_a")

    assert first.inserted == 2
    assert second.duplicates == 2
    signals = await service.list_signals()
    assert all(signal["replay_run_id"] == "replay_a" for signal in signals)


def test_candle_continuity_allows_expected_cross_ist_session_gap() -> None:
    previous_session = _bars(
        count=3,
        start=datetime(2026, 6, 2, 9, 55, tzinfo=timezone.utc),
    )
    current_session = _bars(
        count=3,
        start=datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc),
    )

    assert candle_continuity_ok(previous_session + current_session, timeframe="1minute") is True


def test_candle_continuity_rejects_missing_bar_within_same_ist_session() -> None:
    bars = _bars(count=5)
    bars[3] = _bar(4)

    assert candle_continuity_ok(bars, timeframe="1minute") is False


def test_scanner_candidate_can_use_prior_session_history_without_gap_veto() -> None:
    prior_session = _bars(count=35, start=datetime(2026, 6, 2, 3, 45, tzinfo=timezone.utc))
    current_session = _bars(count=16, start=datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc))
    current_session[-1] = _bar(
        15,
        start=datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc),
        close=Decimal("120"),
        high=Decimal("121"),
        low=Decimal("119"),
        volume=220,
    )
    config = scanner_config_from_settings(
        Settings(scanner_enabled=True, scanner_require_spread_for_future_live=False)
    )

    evaluation = evaluate_strategy(
        strategy_name="opening_range_breakout_long",
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        bars=prior_session + current_session,
        config=config,
    )

    assert DATA_QUALITY_FAILURE not in evaluation.veto_reasons
    assert evaluation.status == CANDIDATE


def test_scanner_routes_require_operator_and_return_no_secrets(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def status(self) -> dict[str, object]:
            return {"enabled": False, "auto_loop": False}

        async def list_signals(self, *, limit: int = 50) -> list[dict[str, object]]:
            return [{"signal_key": "safe", "features": {"indicator_values": {}}}]

    app.dependency_overrides[get_scanner_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        missing = client.get("/api/v1/scanner/status")
        ok = client.get("/api/v1/scanner/signals", headers={"X-Operator-Token": "operator-secret"})
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 200
    rendered = str(ok.json())
    assert "access_token" not in rendered
    assert "operator-secret" not in rendered


def test_scanner_route_refuses_unsupported_timeframe(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def run_once(self, *, symbol: str | None = None, timeframe: str = "1minute") -> object:
            raise ScannerInputError("unsupported timeframe")

    app.dependency_overrides[get_scanner_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/scanner/run-once?symbol=NSE:SBIN&timeframe=5minute",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported timeframe"


@pytest.mark.asyncio
async def test_replay_refuses_unsupported_timeframe(tmp_path) -> None:
    fixture = tmp_path / "bars.json"
    fixture.write_text(
        """
        [
          {"started_at": "2026-06-03T03:45:00Z", "open": "100", "high": "101", "low": "99", "close": "100", "volume": 100}
        ]
        """,
        encoding="utf-8",
    )
    args = argparse.Namespace(
        symbol="NSE:SBIN",
        timeframe="5minute",
        fixture=str(fixture),
        strategy="opening_range_breakout_long",
        replay_run_id="bad_timeframe",
    )

    with pytest.raises(ScannerInputError):
        await run_replay(args)


def test_production_compose_safety_defaults() -> None:
    compose = __import__("pathlib").Path("infra/gcp/docker-compose.prod.yml").read_text()

    assert 'TRADING_MODE: "OFF"' in compose
    assert 'LIVE_ARMED: "false"' in compose
    assert 'SCANNER_ENABLED: "${SCANNER_ENABLED:-false}"' in compose
    assert 'MARKET_DATA_ENABLED: "${MARKET_DATA_ENABLED:-false}"' in compose


def _fresh_now(bars: list[CompletedBar]) -> datetime:
    return bars[-1].started_at + timedelta(minutes=1, seconds=5)


def _candidate_bars() -> list[CompletedBar]:
    bars = _bars(count=51, price=100, volume=100)
    bars[-1] = _bar(50, close=Decimal("120"), high=Decimal("121"), low=Decimal("119"), volume=220)
    return bars


def _bars(
    *,
    count: int,
    start: datetime = datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc),
    price: int = 100,
    volume: int = 100,
) -> list[CompletedBar]:
    return [
        _bar(index, start=start, close=Decimal(price + index % 2), volume=volume)
        for index in range(count)
    ]


def _bar(
    index: int,
    *,
    start: datetime = datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc),
    close: Decimal = Decimal("100"),
    high: Decimal | None = None,
    low: Decimal | None = None,
    volume: int = 100,
) -> CompletedBar:
    return CompletedBar(
        instrument_id=1,
        symbol="NSE:SBIN",
        timeframe="1minute",
        started_at=start + timedelta(minutes=index),
        open_price=close,
        high_price=high or close + Decimal("1"),
        low_price=low or close - Decimal("1"),
        close_price=close,
        volume=volume,
    )
