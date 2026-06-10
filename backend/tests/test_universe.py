from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.analysis.schemas import CompletedBar
from app.api import dependencies
from app.core.config import Settings
from app.main import app
from app.market_data.schemas import InstrumentRecord
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.repository import InMemoryScannerRepository
from app.scanners.service import ScannerService
from app.universe.exceptions import SelectedUniverseMissingError
from app.universe.schemas import UniverseSelectionRun
from app.universe.scoring import score_symbol
from app.universe.service import UniverseSelectionService
from app.universe.validation import UniversePoolValidationService


class InMemoryUniverseRepository:
    def __init__(
        self,
        *,
        instruments: Sequence[InstrumentRecord] = (),
        bars: dict[str, list[CompletedBar]] | None = None,
    ) -> None:
        self.instruments = {item.key: item for item in instruments}
        self.bars = bars or {}
        self.runs: list[UniverseSelectionRun] = []

    async def inspect_instruments(self, symbols: Sequence[str]) -> list[InstrumentRecord]:
        return [self.instruments[symbol] for symbol in symbols if symbol in self.instruments]

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[CompletedBar]:
        return [bar for bar in self.bars.get(symbol, []) if bar.timeframe == timeframe][-limit:]

    async def save_run(self, run: UniverseSelectionRun) -> None:
        self.runs.append(run)

    async def latest_run(self) -> UniverseSelectionRun | None:
        return self.runs[-1] if self.runs else None

    async def list_runs(self, *, limit: int) -> list[UniverseSelectionRun]:
        return list(reversed(self.runs[-limit:]))

    async def get_run(self, run_id: str) -> UniverseSelectionRun | None:
        return next((run for run in self.runs if run.run_id == run_id), None)


def universe_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "universe_selection_enabled": True,
        "universe_selection_pool": "NSE:SBIN",
        "universe_selection_min_session_candles": 51,
        "universe_selection_output_limit": 20,
        "universe_selection_benchmark_symbol": "NSE:NIFTYBEES",
        "scanner_require_spread_for_future_live": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_pool_falls_back_to_market_watchlist() -> None:
    repository = InMemoryUniverseRepository(instruments=[_instrument("SBIN")])
    service = UniversePoolValidationService(
        settings=universe_settings(
            universe_selection_pool="",
            market_data_watchlist="NSE:SBIN",
        ),
        repository=repository,
    )

    result = await service.validate()

    assert result.source == "market_watchlist_fallback"
    assert result.eligible_for_scoring == ["NSE:SBIN"]
    assert "universe_pool_fell_back_to_market_watchlist" in result.warnings


@pytest.mark.asyncio
async def test_valid_explicit_pool_and_file(tmp_path: Path) -> None:
    instruments = [_instrument("SBIN"), _instrument("RELIANCE", token=2)]
    repository = InMemoryUniverseRepository(instruments=instruments)
    explicit = UniversePoolValidationService(
        settings=universe_settings(universe_selection_pool="nse:sbin,NSE:RELIANCE"),
        repository=repository,
    )
    pool_file = tmp_path / "universe.txt"
    pool_file.write_text("# pool\nNSE:SBIN\n\nNSE:RELIANCE\n", encoding="utf-8")
    file_service = UniversePoolValidationService(
        settings=universe_settings(
            universe_selection_pool="",
            universe_selection_pool_file=str(pool_file),
        ),
        repository=repository,
    )

    explicit_result = await explicit.validate()
    file_result = await file_service.validate()

    assert explicit_result.eligible_for_scoring == ["NSE:SBIN", "NSE:RELIANCE"]
    assert file_result.source == "file"
    assert file_result.eligible_for_scoring == ["NSE:SBIN", "NSE:RELIANCE"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pool", "error", "field", "expected"),
    [
        (
            "SBIN",
            "universe_pool_entries_must_use_exchange_colon_tradingsymbol",
            "invalid_format_symbols",
            ["SBIN"],
        ),
        (
            "NSE:SBIN,NSE:SBIN",
            "duplicate_universe_pool_symbol",
            "duplicate_symbols",
            ["NSE:SBIN"],
        ),
        (
            "BSE:SBIN",
            "only_nse_supported_in_current_mvp",
            "non_nse_symbols",
            ["BSE:SBIN"],
        ),
        (
            "NSE:M&M",
            "special_character_symbols_excluded",
            "special_character_symbols",
            ["NSE:M&M"],
        ),
    ],
)
async def test_pool_validation_reports_invalid_entries(
    pool: str,
    error: str,
    field: str,
    expected: list[str],
) -> None:
    result = await UniversePoolValidationService(
        settings=universe_settings(universe_selection_pool=pool),
        repository=InMemoryUniverseRepository(),
    ).validate()

    assert error in result.errors
    assert result.as_dict()[field] == expected


@pytest.mark.asyncio
async def test_pool_reports_missing_inactive_and_over_limit() -> None:
    repository = InMemoryUniverseRepository(
        instruments=[_instrument("SBIN", active=False)]
    )
    result = await UniversePoolValidationService(
        settings=universe_settings(
            universe_selection_pool="NSE:SBIN,NSE:RELIANCE",
            universe_selection_max_pool_symbols=1,
        ),
        repository=repository,
    ).validate()

    assert result.inactive_symbols == ["NSE:SBIN"]
    assert result.missing_symbols == ["NSE:RELIANCE"]
    assert result.over_limit is True


def test_universe_route_requires_operator_token(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")
    client = TestClient(app)

    response = client.get("/api/v1/universe/status")

    assert response.status_code == 401


def test_scoring_computes_metrics_and_score() -> None:
    bars = _multi_session_bars()
    result = score_symbol(
        symbol="NSE:SBIN",
        bars=bars,
        benchmark_bars=_multi_session_bars(symbol="NSE:NIFTYBEES"),
        settings=universe_settings(),
        timeframe="1minute",
        min_candles=51,
        use_current_session=True,
        now=_fresh_now(bars),
    )

    assert result.included is True
    assert result.total_score > 0
    assert result.metrics["atr_pct"] is not None
    assert result.metrics["relative_volume"] is not None
    assert result.component_scores["trend_score"] >= 0


def test_scoring_excludes_insufficient_stale_and_continuity_failure() -> None:
    short = _bars(count=10)
    insufficient = score_symbol(
        symbol="NSE:SBIN",
        bars=short,
        benchmark_bars=[],
        settings=universe_settings(),
        timeframe="1minute",
        min_candles=51,
        use_current_session=True,
        now=_fresh_now(short),
    )
    stale_bars = _multi_session_bars()
    stale = score_symbol(
        symbol="NSE:SBIN",
        bars=stale_bars,
        benchmark_bars=[],
        settings=universe_settings(),
        timeframe="1minute",
        min_candles=51,
        use_current_session=True,
        now=stale_bars[-1].started_at + timedelta(hours=1),
    )
    gap = _multi_session_bars()
    del gap[-10]
    discontinuous = score_symbol(
        symbol="NSE:SBIN",
        bars=gap,
        benchmark_bars=[],
        settings=universe_settings(),
        timeframe="1minute",
        min_candles=40,
        use_current_session=True,
        now=_fresh_now(gap),
    )

    assert "insufficient_candles" in insufficient.exclusion_reasons
    assert "stale_data" in stale.exclusion_reasons
    assert "candle_continuity_failed" in discontinuous.exclusion_reasons
    assert "benchmark_missing" in stale.warnings


def test_scoring_missing_metrics_do_not_crash() -> None:
    bars = _bars(count=51, volume=0)
    result = score_symbol(
        symbol="NSE:SBIN",
        bars=bars,
        benchmark_bars=[],
        settings=universe_settings(),
        timeframe="1minute",
        min_candles=51,
        use_current_session=True,
        now=_fresh_now(bars),
    )

    assert result.metrics["relative_volume"] is None
    assert "relative_volume_unavailable" in result.warnings


@pytest.mark.asyncio
async def test_selection_ranks_top_n_persists_and_retrieves() -> None:
    sbin = _multi_session_bars(volume=300)
    reliance = _multi_session_bars(symbol="NSE:RELIANCE", volume=100)
    benchmark = _multi_session_bars(symbol="NSE:NIFTYBEES", volume=200)
    repository = InMemoryUniverseRepository(
        instruments=[
            _instrument("SBIN"),
            _instrument("RELIANCE", token=2),
            _instrument("NIFTYBEES", token=3),
        ],
        bars={
            "NSE:SBIN": sbin,
            "NSE:RELIANCE": reliance,
            "NSE:NIFTYBEES": benchmark,
        },
    )
    service = UniverseSelectionService(
        settings=universe_settings(
            universe_selection_pool="NSE:SBIN,NSE:RELIANCE",
            universe_selection_output_limit=1,
        ),
        repository=repository,
        now_provider=lambda: _fresh_now(sbin),
    )

    run = await service.select()

    assert run.selected_count == 1
    assert run.ranked_symbols[0]["rank"] == 1
    assert run.selected_symbols == [run.ranked_symbols[0]["symbol"]]
    assert "score_weights" in run.config_snapshot
    assert await service.latest() == run
    assert await service.get_run(run.run_id) == run
    assert await service.list_runs() == [run]


@pytest.mark.asyncio
async def test_selection_dry_run_does_not_persist_and_reports_exclusion() -> None:
    bars = _bars(count=10)
    repository = InMemoryUniverseRepository(
        instruments=[_instrument("SBIN")],
        bars={"NSE:SBIN": bars},
    )
    service = UniverseSelectionService(
        settings=universe_settings(),
        repository=repository,
        now_provider=lambda: _fresh_now(bars),
    )

    run = await service.select(dry_run=True)

    assert repository.runs == []
    assert run.selected_count == 0
    assert run.excluded_symbols[0]["exclusion_reasons"] == ["insufficient_candles"]


@pytest.mark.asyncio
async def test_selection_does_not_mutate_market_watchlist() -> None:
    bars = _multi_session_bars()
    settings = universe_settings(market_data_watchlist="NSE:SBIN")
    repository = InMemoryUniverseRepository(
        instruments=[_instrument("SBIN"), _instrument("NIFTYBEES", token=2)],
        bars={"NSE:SBIN": bars, "NSE:NIFTYBEES": bars},
    )
    service = UniverseSelectionService(
        settings=settings,
        repository=repository,
        now_provider=lambda: _fresh_now(bars),
    )

    await service.select(dry_run=True)

    assert settings.market_data_watchlist == "NSE:SBIN"


@pytest.mark.asyncio
async def test_scanner_batch_uses_latest_universe_and_fails_when_missing() -> None:
    bars = _candidate_bars()
    universe_repository = InMemoryUniverseRepository()
    universe_service = UniverseSelectionService(
        settings=universe_settings(),
        repository=universe_repository,
    )
    scanner = ScannerService(
        settings=Settings(
            scanner_enabled=True,
            scanner_strategies="opening_range_breakout_long",
            scanner_require_spread_for_future_live=False,
        ),
        repository=InMemoryScannerRepository({"NSE:SBIN": bars}),
        latest_universe_provider=universe_service,
        now_provider=lambda: _fresh_now(bars),
    )

    with pytest.raises(SelectedUniverseMissingError):
        await scanner.run_batch(use_latest_universe=True)

    universe_repository.runs.append(_run(["NSE:SBIN"]))
    result = await scanner.run_batch(use_latest_universe=True)

    assert result.evaluated_symbols == 1
    assert result.per_symbol[0].symbol == "NSE:SBIN"


@pytest.mark.asyncio
async def test_auto_loop_selected_universe_defaults_off_and_missing_skips() -> None:
    defaults = Settings()
    assert defaults.scanner_auto_loop_use_selected_universe is False
    repository = InMemoryUniverseRepository()
    universe = UniverseSelectionService(
        settings=universe_settings(),
        repository=repository,
    )
    settings = Settings(
        scanner_enabled=True,
        scanner_auto_loop_enabled=True,
        scanner_auto_loop_use_selected_universe=True,
    )
    scanner = ScannerService(
        settings=settings,
        repository=InMemoryScannerRepository(),
        latest_universe_provider=universe,
    )
    auto = ScannerAutoLoopService(
        settings=settings,
        scanner_service=scanner,
        now_provider=lambda: datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc),
    )

    result = await auto.run_now()

    assert result["skip_reason"] == "selected_universe_missing"
    assert auto.status()["last_error"] == "selected_universe_missing"


def test_universe_defaults_and_compose_safety() -> None:
    settings = Settings()
    compose = Path("infra/gcp/docker-compose.prod.yml").read_text(encoding="utf-8")

    assert settings.universe_selection_enabled is False
    assert settings.universe_selection_use_latest_for_scanner_batch is False
    assert settings.scanner_auto_loop_use_selected_universe is False
    assert settings.paper_enabled is False
    assert settings.paper_mode == "OFF"
    assert 'TRADING_MODE: "OFF"' in compose
    assert 'LIVE_ARMED: "false"' in compose
    assert 'UNIVERSE_SELECTION_ENABLED: "${UNIVERSE_SELECTION_ENABLED:-false}"' in compose


def test_universe_modules_have_no_external_or_execution_imports() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in Path("backend/app/universe").glob("*.py")
    )
    forbidden = (
        "kiteconnect",
        "kiteticker",
        "place_order",
        "modify_order",
        "cancel_order",
        "openai",
        "langgraph",
        "kronos",
        " mcp",
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import beautifulsoup",
        "from bs4",
        "import newspaper",
        "from newspaper",
        "import yfinance",
        "from yfinance",
        "app.paper",
    )

    assert not any(fragment in source for fragment in forbidden)


def _instrument(
    tradingsymbol: str,
    *,
    token: int = 1,
    active: bool = True,
) -> InstrumentRecord:
    return InstrumentRecord(
        id=token,
        exchange="NSE",
        tradingsymbol=tradingsymbol,
        instrument_token=token,
        tick_size=Decimal("0.05"),
        is_active=active,
    )


def _bars(
    *,
    count: int,
    symbol: str = "NSE:SBIN",
    start: datetime = datetime(2026, 6, 3, 3, 45, tzinfo=timezone.utc),
    price: int = 100,
    volume: int = 100,
) -> list[CompletedBar]:
    return [
        CompletedBar(
            instrument_id=1,
            symbol=symbol,
            timeframe="1minute",
            started_at=start + timedelta(minutes=index),
            open_price=Decimal(price + index % 3),
            high_price=Decimal(price + index % 3 + 1),
            low_price=Decimal(price + index % 3 - 1),
            close_price=Decimal(price + index % 3),
            volume=volume + index,
        )
        for index in range(count)
    ]


def _multi_session_bars(
    *,
    symbol: str = "NSE:SBIN",
    volume: int = 100,
) -> list[CompletedBar]:
    prior = _bars(
        count=60,
        symbol=symbol,
        start=datetime(2026, 6, 2, 3, 45, tzinfo=timezone.utc),
        volume=volume,
    )
    current = _bars(count=60, symbol=symbol, volume=volume * 2)
    current[-1] = CompletedBar(
        instrument_id=1,
        symbol=symbol,
        timeframe="1minute",
        started_at=current[-1].started_at,
        open_price=Decimal("120"),
        high_price=Decimal("122"),
        low_price=Decimal("119"),
        close_price=Decimal("121"),
        volume=volume * 4,
    )
    return prior + current


def _candidate_bars() -> list[CompletedBar]:
    bars = _bars(count=51)
    last = bars[-1]
    bars[-1] = CompletedBar(
        instrument_id=last.instrument_id,
        symbol=last.symbol,
        timeframe=last.timeframe,
        started_at=last.started_at,
        open_price=Decimal("120"),
        high_price=Decimal("121"),
        low_price=Decimal("119"),
        close_price=Decimal("120"),
        volume=220,
    )
    return bars


def _fresh_now(bars: list[CompletedBar]) -> datetime:
    return bars[-1].started_at + timedelta(minutes=1, seconds=5)


def _run(symbols: list[str]) -> UniverseSelectionRun:
    now = datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc)
    return UniverseSelectionRun(
        run_id="test-run",
        started_at=now,
        finished_at=now,
        enabled=True,
        timeframe="1minute",
        pool_count=len(symbols),
        scored_count=len(symbols),
        selected_count=len(symbols),
        selected_symbols=symbols,
        ranked_symbols=[],
        excluded_symbols=[],
        errors=[],
        warnings=[],
        config_snapshot={},
    )
