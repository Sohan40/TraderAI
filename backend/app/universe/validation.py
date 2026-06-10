"""Non-throwing universe-pool parsing and local instrument validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.universe.repository import UniverseRepository
from app.universe.schemas import UniversePoolValidation

_PLAIN_SYMBOL = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class UniversePoolSource:
    source: str
    entries: list[str]
    errors: list[str]
    warnings: list[str]


class UniversePoolValidationService:
    def __init__(self, *, settings: Settings, repository: UniverseRepository) -> None:
        self._settings = settings
        self._repository = repository

    async def validate(self, symbols: list[str] | None = None) -> UniversePoolValidation:
        source = _load_source(self._settings, symbols)
        parsed: list[str] = []
        normalized: list[str] = []
        invalid: list[str] = []
        duplicates: list[str] = []
        non_nse: list[str] = []
        special: list[str] = []
        seen: set[str] = set()
        for entry in source.entries:
            if entry.count(":") != 1:
                invalid.append(entry)
                continue
            exchange, tradingsymbol = (part.strip().upper() for part in entry.split(":", 1))
            if not exchange or not tradingsymbol:
                invalid.append(entry)
                continue
            key = f"{exchange}:{tradingsymbol}"
            parsed.append(entry)
            if exchange != "NSE":
                non_nse.append(key)
            if not _PLAIN_SYMBOL.fullmatch(tradingsymbol):
                special.append(key)
            if key in seen:
                duplicates.append(key)
            else:
                seen.add(key)
                normalized.append(key)

        over_limit = (
            self._settings.universe_selection_max_pool_symbols < 1
            or len(source.entries) > self._settings.universe_selection_max_pool_symbols
        )
        errors = list(source.errors)
        if not source.entries:
            errors.append("universe_pool_empty")
        if invalid:
            errors.append("universe_pool_entries_must_use_exchange_colon_tradingsymbol")
        if duplicates:
            errors.append("duplicate_universe_pool_symbol")
        if non_nse:
            errors.append("only_nse_supported_in_current_mvp")
        if special and self._settings.universe_selection_exclude_special_char_symbols:
            errors.append("special_character_symbols_excluded")
        if over_limit:
            errors.append("universe_pool_exceeds_configured_maximum")

        syntactically_eligible = [
            symbol
            for symbol in normalized
            if symbol not in non_nse
            and not (
                self._settings.universe_selection_exclude_special_char_symbols
                and symbol in special
            )
        ]
        records = await self._repository.inspect_instruments(syntactically_eligible)
        record_by_key = {record.key: record for record in records}
        missing = sorted(symbol for symbol in syntactically_eligible if symbol not in record_by_key)
        inactive = sorted(
            symbol
            for symbol in syntactically_eligible
            if symbol in record_by_key and not record_by_key[symbol].is_active
        )
        active = sorted(
            symbol
            for symbol in syntactically_eligible
            if symbol in record_by_key and record_by_key[symbol].is_active
        )
        eligible = [
            symbol
            for symbol in syntactically_eligible
            if symbol not in missing
            and (
                not self._settings.universe_selection_require_active_instrument
                or symbol not in inactive
            )
        ]
        if missing:
            errors.append("universe_pool_symbols_not_synced")
        if inactive and self._settings.universe_selection_require_active_instrument:
            errors.append("universe_pool_symbols_inactive")
        return UniversePoolValidation(
            source=source.source,
            configured_count=len(source.entries),
            max_pool_symbols=self._settings.universe_selection_max_pool_symbols,
            parsed_symbols=parsed,
            normalized_symbols=normalized,
            invalid_format_symbols=invalid,
            duplicate_symbols=sorted(set(duplicates)),
            non_nse_symbols=sorted(set(non_nse)),
            special_character_symbols=sorted(set(special)),
            over_limit=over_limit,
            active_symbols=active,
            missing_symbols=missing,
            inactive_symbols=inactive,
            eligible_for_scoring=eligible,
            errors=_unique(errors),
            warnings=_unique(source.warnings),
        )


def _load_source(settings: Settings, symbols: list[str] | None) -> UniversePoolSource:
    if symbols is not None:
        return UniversePoolSource("request", symbols, [], [])
    if settings.universe_selection_pool_file:
        warnings = (
            ["universe_pool_file_overrides_environment_string"]
            if settings.universe_selection_pool.strip()
            else []
        )
        try:
            lines = Path(settings.universe_selection_pool_file).read_text(
                encoding="utf-8"
            ).splitlines()
        except (OSError, UnicodeError):
            return UniversePoolSource(
                "file",
                [],
                ["universe_pool_file_unreadable"],
                warnings,
            )
        return UniversePoolSource(
            "file",
            [
                line.strip()
                for line in lines
                if line.strip() and not line.lstrip().startswith("#")
            ],
            [],
            warnings,
        )
    if settings.universe_selection_pool.strip():
        return UniversePoolSource(
            "environment",
            [
                item.strip()
                for item in settings.universe_selection_pool.split(",")
                if item.strip()
            ],
            [],
            [],
        )
    return UniversePoolSource(
        "market_watchlist_fallback",
        [
            item.strip()
            for item in settings.market_data_watchlist.split(",")
            if item.strip()
        ],
        [],
        ["universe_pool_fell_back_to_market_watchlist"],
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
