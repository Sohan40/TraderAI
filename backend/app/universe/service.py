"""Deterministic universe selection orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from app.core.config import Settings
from app.universe.exceptions import UniverseInputError, UniverseSelectionDisabledError
from app.universe.repository import UniverseRepository
from app.universe.schemas import UniverseSelectionRun, UniverseSymbolResult
from app.universe.scoring import SCORE_WEIGHTS, score_symbol
from app.universe.validation import UniversePoolValidationService


class UniverseSelectionService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: UniverseRepository,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._validation = UniversePoolValidationService(
            settings=settings,
            repository=repository,
        )
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def status(self) -> dict[str, object]:
        latest = await self._repository.latest_run()
        pool = await self._validation.validate()
        return {
            "enabled": self._settings.universe_selection_enabled,
            "store_runs": self._settings.universe_selection_store_runs,
            "output_limit": self._settings.universe_selection_output_limit,
            "timeframe": self._settings.universe_selection_timeframe,
            "use_latest_for_scanner_batch": (
                self._settings.universe_selection_use_latest_for_scanner_batch
            ),
            "auto_loop_use_selected_universe": (
                self._settings.scanner_auto_loop_use_selected_universe
            ),
            "latest_run_at": latest.finished_at.isoformat() if latest else None,
            "latest_selected_count": latest.selected_count if latest else 0,
            "latest_selected_symbols": latest.selected_symbols if latest else [],
            "pool_valid": not pool.errors,
        }

    async def validate_pool(self, symbols: list[str] | None = None) -> dict[str, object]:
        return (await self._validation.validate(symbols)).as_dict()

    async def select(
        self,
        *,
        limit: int | None = None,
        timeframe: str | None = None,
        dry_run: bool = False,
        include_excluded: bool = True,
        use_current_session: bool = True,
        min_candles: int | None = None,
        symbols: list[str] | None = None,
    ) -> UniverseSelectionRun:
        if not self._settings.universe_selection_enabled:
            raise UniverseSelectionDisabledError("Universe selection is disabled.")
        selected_timeframe = timeframe or self._settings.universe_selection_timeframe
        if selected_timeframe != "1minute":
            raise UniverseInputError("Universe selection supports only 1minute candles.")
        output_limit = limit or self._settings.universe_selection_output_limit
        if output_limit < 1 or output_limit > self._settings.universe_selection_max_pool_symbols:
            raise UniverseInputError("Universe output limit is invalid.")
        required_candles = min_candles or self._settings.universe_selection_min_session_candles
        if required_candles < 1:
            raise UniverseInputError("Universe minimum candles must be positive.")

        started = self._now()
        validation = await self._validation.validate(symbols)
        benchmark_symbol = self._settings.universe_selection_benchmark_symbol
        candle_limit = max(
            required_candles,
            self._settings.universe_selection_lookback_days * 375,
        )
        benchmark_bars = (
            await self._repository.load_completed_bars(
                symbol=benchmark_symbol,
                timeframe=selected_timeframe,
                limit=candle_limit,
            )
            if benchmark_symbol
            else []
        )
        results: list[UniverseSymbolResult] = []
        validation_exclusions = _validation_exclusions(validation.as_dict())
        results.extend(validation_exclusions)
        for symbol in validation.eligible_for_scoring:
            bars = await self._repository.load_completed_bars(
                symbol=symbol,
                timeframe=selected_timeframe,
                limit=candle_limit,
            )
            results.append(
                score_symbol(
                    symbol=symbol,
                    bars=bars,
                    benchmark_bars=benchmark_bars,
                    settings=self._settings,
                    timeframe=selected_timeframe,
                    min_candles=required_candles,
                    use_current_session=use_current_session,
                    now=started,
                    active_instrument=symbol not in validation.inactive_symbols,
                )
            )

        included = sorted(
            (item for item in results if item.included),
            key=lambda item: (-item.total_score, item.symbol),
        )
        ranked = [replace(item, rank=index) for index, item in enumerate(included, start=1)]
        chosen = ranked[:output_limit]
        excluded = [item for item in results if not item.included]
        finished = self._now()
        warnings = list(validation.warnings)
        if not benchmark_bars:
            warnings.append("benchmark_missing")
        run = UniverseSelectionRun(
            run_id=uuid4().hex,
            started_at=started,
            finished_at=finished,
            enabled=True,
            timeframe=selected_timeframe,
            pool_count=validation.configured_count,
            scored_count=len(ranked),
            selected_count=len(chosen),
            selected_symbols=[item.symbol for item in chosen],
            ranked_symbols=[item.as_dict() for item in ranked],
            excluded_symbols=(
                [item.as_dict() for item in excluded] if include_excluded else []
            ),
            errors=list(validation.errors),
            warnings=list(dict.fromkeys(warnings)),
            config_snapshot=self._config_snapshot(
                output_limit=output_limit,
                min_candles=required_candles,
                use_current_session=use_current_session,
            ),
        )
        if self._settings.universe_selection_store_runs and not dry_run:
            await self._repository.save_run(run)
        return run

    async def latest(self) -> UniverseSelectionRun | None:
        return await self._repository.latest_run()

    async def list_runs(self, *, limit: int = 20) -> list[UniverseSelectionRun]:
        return await self._repository.list_runs(limit=max(1, min(limit, 100)))

    async def get_run(self, run_id: str) -> UniverseSelectionRun | None:
        return await self._repository.get_run(run_id)

    async def latest_selected_symbols(self) -> list[str] | None:
        latest = await self._repository.latest_run()
        return latest.selected_symbols if latest else None

    def _config_snapshot(
        self,
        *,
        output_limit: int,
        min_candles: int,
        use_current_session: bool,
    ) -> dict[str, object]:
        return {
            "output_limit": output_limit,
            "min_session_candles": min_candles,
            "lookback_days": self._settings.universe_selection_lookback_days,
            "require_active_instrument": (
                self._settings.universe_selection_require_active_instrument
            ),
            "require_continuity": self._settings.universe_selection_require_continuity,
            "benchmark_symbol": self._settings.universe_selection_benchmark_symbol,
            "min_price": self._settings.universe_selection_min_price,
            "max_price": self._settings.universe_selection_max_price,
            "min_avg_turnover": self._settings.universe_selection_min_avg_turnover,
            "min_atr_pct": self._settings.universe_selection_min_atr_pct,
            "max_atr_pct": self._settings.universe_selection_max_atr_pct,
            "use_current_session": use_current_session,
            "score_weights": SCORE_WEIGHTS,
        }

    def _now(self) -> datetime:
        now = self._now_provider()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _validation_exclusions(validation: dict[str, object]) -> list[UniverseSymbolResult]:
    reasons_by_symbol: dict[str, list[str]] = {}
    mappings = (
        ("missing_symbols", "missing_instrument"),
        ("inactive_symbols", "inactive_instrument"),
        ("special_character_symbols", "special_character_symbol"),
    )
    for field, reason in mappings:
        for symbol in cast(list[str], validation[field]):
            reasons_by_symbol.setdefault(str(symbol), []).append(reason)
    return [
        UniverseSymbolResult(
            symbol=symbol,
            rank=None,
            total_score=0.0,
            component_scores={key: 0.0 for key in SCORE_WEIGHTS},
            metrics={},
            included=False,
            exclusion_reasons=reasons,
            warnings=[],
        )
        for symbol, reasons in sorted(reasons_by_symbol.items())
    ]
