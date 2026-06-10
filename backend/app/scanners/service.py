"""Operator-triggered deterministic scanner service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.analysis.feature_builder import build_feature_input
from app.analysis.indicators import IST, NSE_OPEN, candle_continuity_ok
from app.analysis.schemas import CompletedBar
from app.core.config import Settings
from app.market_data.watchlist_validation import strict_configured_watchlist
from app.scanners.exceptions import ScannerConfigError, ScannerDisabledError, ScannerInputError
from app.scanners.repository import ScannerRepository
from app.scanners.schemas import (
    CANDIDATE,
    P05_STRATEGIES,
    REJECTED_SIGNAL,
    SCANNER_TIMEFRAME,
    ScannerBatchResult,
    ScannerConfig,
    ScannerRunResult,
    ScannerSymbolResult,
)
from app.scanners.strategies import evaluate_strategy
from app.universe.exceptions import SelectedUniverseMissingError

SCANNER_HISTORY_BAR_LIMIT = 800
SCANNER_REPLAY_BAR_LIMIT = 100_000


class LatestUniverseProvider(Protocol):
    async def latest_selected_symbols(self) -> list[str] | None: ...


class ScannerService:
    """Run deterministic P05 scanners over stored completed candles only."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: ScannerRepository,
        now_provider: Callable[[], datetime] | None = None,
        latest_universe_provider: LatestUniverseProvider | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._config = scanner_config_from_settings(settings)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._latest_universe_provider = latest_universe_provider

    async def status(self) -> dict[str, object]:
        return {
            "enabled": self._config.enabled,
            "observation_mode": self._config.observation_mode,
            "strategies": self._config.strategies,
            "auto_loop": self._settings.scanner_auto_loop_enabled,
            "use_latest_universe_default": (
                self._settings.universe_selection_use_latest_for_scanner_batch
            ),
        }

    async def run_once(
        self,
        *,
        symbol: str | None = None,
        timeframe: str = "1minute",
        replay_run_id: str | None = None,
    ) -> ScannerRunResult:
        self._validate_timeframe(timeframe)
        if not self._config.enabled and replay_run_id is None:
            raise ScannerDisabledError("Scanner is disabled.")
        symbols = [symbol] if symbol else await self._repository.load_symbols()
        evaluated = inserted = duplicates = candidates = rejected = 0
        veto_counter: Counter[str] = Counter()
        for current_symbol in symbols:
            symbol_result, symbol_vetoes = await self._run_symbol(
                symbol=current_symbol,
                timeframe=timeframe,
                replay_run_id=replay_run_id,
                store_rejections=True,
                dry_run=False,
            )
            evaluated += symbol_result.evaluated
            inserted += symbol_result.inserted
            duplicates += symbol_result.duplicates
            candidates += symbol_result.candidates
            rejected += symbol_result.rejected
            veto_counter.update(symbol_vetoes)
        return ScannerRunResult(
            evaluated=evaluated,
            inserted=inserted,
            duplicates=duplicates,
            candidates=candidates,
            rejected=rejected,
            veto_counts=dict(sorted(veto_counter.items())),
        )

    async def run_batch(
        self,
        *,
        symbols: list[str] | None = None,
        timeframe: str = SCANNER_TIMEFRAME,
        store_rejections: bool = True,
        dry_run: bool = False,
        max_symbols: int | None = None,
        min_candles: int = 0,
        require_session_start: bool = False,
        require_continuity: bool = False,
        use_latest_universe: bool = False,
    ) -> ScannerBatchResult:
        """Scan multiple symbols over stored completed candles only."""
        self._validate_timeframe(timeframe)
        if not self._config.enabled:
            raise ScannerDisabledError("Scanner is disabled.")
        use_selected = (
            use_latest_universe
            or self._settings.universe_selection_use_latest_for_scanner_batch
        )
        if symbols is not None and use_selected:
            raise ScannerInputError(
                "Explicit symbols cannot be combined with selected universe."
            )
        if use_selected:
            if self._latest_universe_provider is None:
                raise SelectedUniverseMissingError("Selected universe missing.")
            selected = await self._latest_universe_provider.latest_selected_symbols()
            if not selected:
                raise SelectedUniverseMissingError("Selected universe missing.")
        else:
            selected = symbols or [
                item.key for item in strict_configured_watchlist(self._settings)
            ]
        normalized = _normalize_symbols(selected)
        limit = max_symbols or self._settings.market_data_max_instruments
        if limit < 1 or len(normalized) > limit:
            raise ScannerInputError("Scanner batch exceeds configured symbol maximum.")
        started_at = self._now_provider()
        per_symbol: list[ScannerSymbolResult] = []
        errors: dict[str, str] = {}
        for symbol in normalized:
            try:
                result, _ = await self._run_symbol(
                    symbol=symbol,
                    timeframe=timeframe,
                    replay_run_id=None,
                    store_rejections=store_rejections,
                    dry_run=dry_run,
                    min_candles=min_candles,
                    require_session_start=require_session_start,
                    require_continuity=require_continuity,
                )
            except Exception:
                result = ScannerSymbolResult(symbol=symbol, error="symbol_scan_failed")
                errors[symbol] = "symbol_scan_failed"
            per_symbol.append(result)
        finished_at = self._now_provider()
        return ScannerBatchResult(
            evaluated_symbols=len(normalized),
            total_evaluated=sum(item.evaluated for item in per_symbol),
            total_inserted=sum(item.inserted for item in per_symbol),
            total_duplicates=sum(item.duplicates for item in per_symbol),
            total_candidates=sum(item.candidates for item in per_symbol),
            total_rejected=sum(item.rejected for item in per_symbol),
            per_symbol=per_symbol,
            errors=errors,
            started_at=started_at,
            finished_at=finished_at,
        )

    async def run_replay(
        self,
        *,
        symbol: str,
        timeframe: str,
        replay_run_id: str,
    ) -> ScannerRunResult:
        """Replay completed bars chronologically without leaking future candles."""
        self._validate_timeframe(timeframe)
        bars = await self._repository.load_completed_bars(
            symbol=symbol,
            timeframe=timeframe,
            limit=SCANNER_REPLAY_BAR_LIMIT,
        )
        ordered_bars = sorted(bars, key=lambda bar: bar.started_at)
        benchmark_bars = None
        if self._config.benchmark_symbol:
            benchmark_bars = sorted(
                await self._repository.load_completed_bars(
                    symbol=self._config.benchmark_symbol,
                    timeframe=timeframe,
                    limit=SCANNER_REPLAY_BAR_LIMIT,
                ),
                key=lambda bar: bar.started_at,
            )
        evaluated = inserted = duplicates = candidates = rejected = 0
        veto_counter: Counter[str] = Counter()
        for index, current_bar in enumerate(ordered_bars):
            prefix = ordered_bars[: index + 1]
            benchmark_prefix = None
            if benchmark_bars is not None:
                benchmark_prefix = [
                    bar for bar in benchmark_bars if bar.started_at <= current_bar.started_at
                ]
            for strategy_name in self._config.strategies:
                evaluation = evaluate_strategy(
                    strategy_name=strategy_name,
                    instrument_id=current_bar.instrument_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    bars=prefix,
                    config=self._config,
                    benchmark_bars=benchmark_prefix,
                    quote_context=None,
                    replay_run_id=replay_run_id,
                    is_stale=False,
                )
                evaluated += 1
                candidates += int(evaluation.status == CANDIDATE)
                rejected += int(evaluation.status == REJECTED_SIGNAL)
                veto_counter.update(evaluation.veto_reasons)
                if await self._repository.insert_signal(evaluation):
                    inserted += 1
                else:
                    duplicates += 1
                    veto_counter.update(["duplicate_signal"])
        return ScannerRunResult(
            evaluated=evaluated,
            inserted=inserted,
            duplicates=duplicates,
            candidates=candidates,
            rejected=rejected,
            veto_counts=dict(sorted(veto_counter.items())),
        )

    def _latest_completed_bar_is_stale(
        self,
        *,
        bars: list[CompletedBar],
        replay_run_id: str | None,
    ) -> bool:
        if replay_run_id is not None or not bars:
            return False
        latest = bars[-1]
        bar_end = latest.started_at + timedelta(minutes=1)
        stale_after = bar_end + timedelta(minutes=1, seconds=self._config.stale_after_seconds)
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc) > stale_after.astimezone(timezone.utc)

    async def _run_symbol(
        self,
        *,
        symbol: str,
        timeframe: str,
        replay_run_id: str | None,
        store_rejections: bool,
        dry_run: bool,
        min_candles: int = 0,
        require_session_start: bool = False,
        require_continuity: bool = False,
    ) -> tuple[ScannerSymbolResult, Counter[str]]:
        bars = await self._repository.load_completed_bars(
            symbol=symbol,
            timeframe=timeframe,
            limit=SCANNER_HISTORY_BAR_LIMIT,
        )
        if not bars:
            return ScannerSymbolResult(symbol=symbol, skipped_reason="no_completed_candles"), Counter()
        current_session = build_feature_input(bars).current_session_bars
        if min_candles and len(current_session) < min_candles:
            return (
                ScannerSymbolResult(symbol=symbol, skipped_reason="insufficient_session_candles"),
                Counter(),
            )
        if require_session_start and (
            not current_session
            or current_session[0].started_at.astimezone(IST).time() != NSE_OPEN
        ):
            return (
                ScannerSymbolResult(symbol=symbol, skipped_reason="session_start_missing"),
                Counter(),
            )
        if require_continuity and not candle_continuity_ok(
            current_session,
            timeframe=timeframe,
        ):
            return (
                ScannerSymbolResult(symbol=symbol, skipped_reason="session_candle_gap"),
                Counter(),
            )
        is_stale = self._latest_completed_bar_is_stale(
            bars=bars,
            replay_run_id=replay_run_id,
        )
        benchmark_bars = None
        if self._config.benchmark_symbol:
            benchmark_bars = await self._repository.load_completed_bars(
                symbol=self._config.benchmark_symbol,
                timeframe=timeframe,
                limit=SCANNER_HISTORY_BAR_LIMIT,
            )
        evaluated = inserted = duplicates = candidates = rejected = 0
        veto_counter: Counter[str] = Counter()
        for strategy_name in self._config.strategies:
            evaluation = evaluate_strategy(
                strategy_name=strategy_name,
                instrument_id=bars[-1].instrument_id,
                symbol=symbol,
                timeframe=timeframe,
                bars=bars,
                config=self._config,
                benchmark_bars=benchmark_bars,
                quote_context=None,
                replay_run_id=replay_run_id,
                is_stale=is_stale,
            )
            evaluated += 1
            candidates += int(evaluation.status == CANDIDATE)
            rejected += int(evaluation.status == REJECTED_SIGNAL)
            veto_counter.update(evaluation.veto_reasons)
            should_persist = evaluation.status == CANDIDATE or store_rejections
            if should_persist and not dry_run:
                if await self._repository.insert_signal(evaluation):
                    inserted += 1
                else:
                    duplicates += 1
                    veto_counter.update(["duplicate_signal"])
        return (
            ScannerSymbolResult(
                symbol=symbol,
                evaluated=evaluated,
                inserted=inserted,
                duplicates=duplicates,
                candidates=candidates,
                rejected=rejected,
            ),
            veto_counter,
        )

    def _validate_timeframe(self, timeframe: str) -> None:
        if timeframe != SCANNER_TIMEFRAME:
            raise ScannerInputError("Scanner supports only 1minute completed candles in P05.")

    async def list_signals(self, *, limit: int = 50) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 200))
        records = await self._repository.list_signals(limit=bounded_limit)
        return [
            {
                "id": record.id,
                "signal_key": record.signal_key,
                "symbol": record.symbol,
                "strategy_name": record.strategy_name,
                "strategy_version": record.strategy_version,
                "signal_status": record.signal_status,
                "signal_time": record.signal_time.isoformat(),
                "direction": record.direction,
                "veto_reasons": record.veto_reasons,
                "replay_run_id": record.replay_run_id,
                "features": record.features,
            }
            for record in records
        ]


def scanner_config_from_settings(settings: Settings) -> ScannerConfig:
    strategies = [item.strip() for item in settings.scanner_strategies.split(",") if item.strip()]
    unsupported = [strategy for strategy in strategies if strategy not in P05_STRATEGIES]
    if unsupported:
        raise ScannerConfigError("Unsupported scanner strategy configured.")
    return ScannerConfig(
        enabled=settings.scanner_enabled,
        strategies=strategies,
        observation_mode=settings.scanner_observation_mode,
        future_live_eligible_strategy=settings.scanner_future_live_eligible_strategy,
        opening_range_minutes=settings.scanner_opening_range_minutes,
        stale_after_seconds=settings.scanner_stale_after_seconds,
        min_volume_ratio=settings.scanner_min_volume_ratio,
        max_spread_pct=settings.scanner_max_spread_pct,
        require_spread_for_future_live=settings.scanner_require_spread_for_future_live,
        benchmark_symbol=settings.scanner_benchmark_symbol or None,
    )


def _normalize_symbols(symbols: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        value = raw.strip().upper()
        if not value or value.count(":") != 1:
            raise ScannerInputError("Scanner symbols must use EXCHANGE:TRADINGSYMBOL.")
        exchange, tradingsymbol = value.split(":", 1)
        if exchange != "NSE" or not tradingsymbol:
            raise ScannerInputError("Scanner batch supports NSE symbols only.")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    if not normalized:
        raise ScannerInputError("Scanner batch symbol list is empty.")
    return normalized
