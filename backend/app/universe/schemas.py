"""Typed universe-selection results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UniversePoolValidation:
    source: str
    configured_count: int
    max_pool_symbols: int
    parsed_symbols: list[str]
    normalized_symbols: list[str]
    invalid_format_symbols: list[str]
    duplicate_symbols: list[str]
    non_nse_symbols: list[str]
    special_character_symbols: list[str]
    over_limit: bool
    active_symbols: list[str]
    missing_symbols: list[str]
    inactive_symbols: list[str]
    eligible_for_scoring: list[str]
    errors: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class UniverseSymbolResult:
    symbol: str
    rank: int | None
    total_score: float
    component_scores: dict[str, float]
    metrics: dict[str, object]
    included: bool
    exclusion_reasons: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class UniverseSelectionRun:
    run_id: str
    started_at: datetime
    finished_at: datetime
    enabled: bool
    timeframe: str
    pool_count: int
    scored_count: int
    selected_count: int
    selected_symbols: list[str]
    ranked_symbols: list[dict[str, object]]
    excluded_symbols: list[dict[str, object]]
    errors: list[str]
    warnings: list[str]
    config_snapshot: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": duration_ms,
            "enabled": self.enabled,
            "timeframe": self.timeframe,
            "pool_count": self.pool_count,
            "scored_count": self.scored_count,
            "selected_count": self.selected_count,
            "selected_symbols": self.selected_symbols,
            "ranked_symbols": self.ranked_symbols,
            "excluded_symbols": self.excluded_symbols,
            "errors": self.errors,
            "warnings": self.warnings,
            "config_snapshot": self.config_snapshot,
        }
