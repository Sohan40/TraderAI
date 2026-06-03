"""Operator-triggered deterministic scanner service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.analysis.schemas import CompletedBar
from app.core.config import Settings
from app.scanners.exceptions import ScannerConfigError, ScannerDisabledError
from app.scanners.repository import ScannerRepository
from app.scanners.schemas import CANDIDATE, P05_STRATEGIES, REJECTED_SIGNAL, ScannerConfig, ScannerRunResult
from app.scanners.strategies import evaluate_strategy

MIN_REQUIRED_BARS = 51


class ScannerService:
    """Run deterministic P05 scanners over stored completed candles only."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: ScannerRepository,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._config = scanner_config_from_settings(settings)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def status(self) -> dict[str, object]:
        return {
            "enabled": self._config.enabled,
            "observation_mode": self._config.observation_mode,
            "strategies": self._config.strategies,
            "auto_loop": False,
        }

    async def run_once(
        self,
        *,
        symbol: str | None = None,
        timeframe: str = "1minute",
        replay_run_id: str | None = None,
    ) -> ScannerRunResult:
        if not self._config.enabled and replay_run_id is None:
            raise ScannerDisabledError("Scanner is disabled.")
        symbols = [symbol] if symbol else await self._repository.load_symbols()
        evaluated = inserted = duplicates = candidates = rejected = 0
        veto_counter: Counter[str] = Counter()
        for current_symbol in symbols:
            bars = await self._repository.load_completed_bars(
                symbol=current_symbol,
                timeframe=timeframe,
                limit=200,
            )
            if not bars:
                continue
            is_stale = self._latest_completed_bar_is_stale(
                bars=bars,
                timeframe=timeframe,
                replay_run_id=replay_run_id,
            )
            benchmark_bars = None
            if self._config.benchmark_symbol:
                benchmark_bars = await self._repository.load_completed_bars(
                    symbol=self._config.benchmark_symbol,
                    timeframe=timeframe,
                    limit=200,
                )
            for strategy_name in self._config.strategies:
                evaluation = evaluate_strategy(
                    strategy_name=strategy_name,
                    instrument_id=bars[-1].instrument_id,
                    symbol=current_symbol,
                    timeframe=timeframe,
                    bars=bars[-MIN_REQUIRED_BARS:],
                    config=self._config,
                    benchmark_bars=benchmark_bars[-MIN_REQUIRED_BARS:] if benchmark_bars else None,
                    quote_context=None,
                    replay_run_id=replay_run_id,
                    is_stale=is_stale,
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
        timeframe: str,
        replay_run_id: str | None,
    ) -> bool:
        if replay_run_id is not None or not bars:
            return False
        latest = bars[-1]
        if timeframe != "1minute":
            return False
        bar_end = latest.started_at + timedelta(minutes=1)
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc) - bar_end.astimezone(timezone.utc) > timedelta(
            seconds=self._config.stale_after_seconds
        )

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
