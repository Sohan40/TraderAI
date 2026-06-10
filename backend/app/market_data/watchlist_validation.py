"""Non-throwing watchlist diagnostics backed by configuration and local storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.market_data.exceptions import WatchlistError
from app.market_data.repository import MarketDataRepository
from app.market_data.schemas import InstrumentRecord, WatchlistSymbol
from app.market_data.watchlist import MVP_EXCHANGE, parse_watchlist


@dataclass(frozen=True)
class WatchlistSource:
    """Loaded watchlist text and safe source metadata."""

    raw_watchlist: str
    entries: list[str]
    blank_entries: list[int]
    source: str
    warnings: list[str]
    errors: list[str]


@dataclass(frozen=True)
class WatchlistValidationResult:
    """Complete operator-safe watchlist validation result."""

    raw_watchlist: str
    source: str
    configured_count: int
    max_instruments: int
    parsed_symbols: list[str]
    normalized_symbols: list[str]
    invalid_format_symbols: list[str]
    duplicate_symbols: list[str]
    non_nse_symbols: list[str]
    blank_entries: list[int]
    over_limit: bool
    resolved_symbols: list[str]
    missing_symbols: list[str]
    inactive_symbols: list[str]
    unresolved_symbols: list[str]
    ready_for_instrument_sync: bool
    ready_for_stream: bool
    errors: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_watchlist": self.raw_watchlist,
            "source": self.source,
            "configured_count": self.configured_count,
            "max_instruments": self.max_instruments,
            "parsed_symbols": self.parsed_symbols,
            "normalized_symbols": self.normalized_symbols,
            "invalid_format_symbols": self.invalid_format_symbols,
            "duplicate_symbols": self.duplicate_symbols,
            "non_nse_symbols": self.non_nse_symbols,
            "blank_entries": self.blank_entries,
            "over_limit": self.over_limit,
            "resolved_symbols": self.resolved_symbols,
            "missing_symbols": self.missing_symbols,
            "inactive_symbols": self.inactive_symbols,
            "unresolved_symbols": self.unresolved_symbols,
            "ready_for_instrument_sync": self.ready_for_instrument_sync,
            "ready_for_stream": self.ready_for_stream,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class DiagnosedWatchlist:
    """Parsed watchlist details before local instrument resolution."""

    configured_count: int
    parsed_symbols: list[str]
    normalized_symbols: list[str]
    invalid_format_symbols: list[str]
    duplicate_symbols: list[str]
    non_nse_symbols: list[str]
    over_limit: bool
    symbols: list[WatchlistSymbol]
    errors: list[str]
    warnings: list[str]


class WatchlistValidationService:
    """Validate configured watchlist without calling broker APIs."""

    def __init__(self, *, settings: Settings, repository: MarketDataRepository) -> None:
        self._settings = settings
        self._repository = repository

    async def validate(self) -> WatchlistValidationResult:
        source = load_watchlist_source(self._settings)
        parsed = _diagnose_entries(source=source, max_instruments=self._settings.market_data_max_instruments)
        records: list[InstrumentRecord] = []
        if parsed.symbols:
            records = await self._repository.inspect_watchlist(parsed.symbols)
        record_by_key = {record.key: record for record in records}
        normalized = parsed.normalized_symbols
        resolved = sorted(key for key in normalized if key in record_by_key)
        missing = sorted(key for key in normalized if key not in record_by_key)
        inactive = sorted(
            key for key in normalized if key in record_by_key and not record_by_key[key].is_active
        )
        unresolved = sorted(set(missing + inactive))
        errors = list(source.errors) + list(parsed.errors)
        if missing:
            errors.append("watchlist_symbols_not_synced")
        if inactive:
            errors.append("watchlist_symbols_inactive")
        errors = _unique(errors)
        warnings = _unique(source.warnings + list(parsed.warnings))
        ready_for_instrument_sync = not source.errors and not parsed.errors
        ready_for_stream = ready_for_instrument_sync and not missing and not inactive
        return WatchlistValidationResult(
            raw_watchlist=source.raw_watchlist,
            source=source.source,
            configured_count=parsed.configured_count,
            max_instruments=self._settings.market_data_max_instruments,
            parsed_symbols=parsed.parsed_symbols,
            normalized_symbols=normalized,
            invalid_format_symbols=parsed.invalid_format_symbols,
            duplicate_symbols=parsed.duplicate_symbols,
            non_nse_symbols=parsed.non_nse_symbols,
            blank_entries=source.blank_entries,
            over_limit=parsed.over_limit,
            resolved_symbols=resolved,
            missing_symbols=missing,
            inactive_symbols=inactive,
            unresolved_symbols=unresolved,
            ready_for_instrument_sync=ready_for_instrument_sync,
            ready_for_stream=ready_for_stream,
            errors=errors,
            warnings=warnings,
        )


def load_watchlist_source(settings: Settings) -> WatchlistSource:
    """Load env or optional newline file watchlist without validating entries."""
    warnings: list[str] = []
    errors: list[str] = []
    if settings.market_data_watchlist_file:
        if settings.market_data_watchlist.strip():
            warnings.append("watchlist_file_overrides_environment_string")
        path = Path(settings.market_data_watchlist_file)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return WatchlistSource(
                raw_watchlist="",
                entries=[],
                blank_entries=[],
                source="file",
                warnings=warnings,
                errors=["watchlist_file_unreadable"],
            )
        entries = [
            line.strip()
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return WatchlistSource(
            raw_watchlist=",".join(entries),
            entries=entries,
            blank_entries=[],
            source="file",
            warnings=warnings,
            errors=errors,
        )

    raw_entries = settings.market_data_watchlist.split(",")
    blank_entries = [index for index, entry in enumerate(raw_entries, start=1) if not entry.strip()]
    entries = [entry.strip() for entry in raw_entries if entry.strip()]
    return WatchlistSource(
        raw_watchlist=settings.market_data_watchlist,
        entries=entries,
        blank_entries=blank_entries,
        source="environment",
        warnings=warnings,
        errors=errors,
    )


def strict_configured_watchlist(settings: Settings) -> list[WatchlistSymbol]:
    """Load the configured source and preserve the existing strict parser contract."""
    source = load_watchlist_source(settings)
    if source.errors:
        raise WatchlistError("Configured watchlist file could not be read.")
    return parse_watchlist(source.raw_watchlist, settings.market_data_max_instruments)


def configured_watchlist_entries(settings: Settings) -> list[str]:
    """Return loaded entries for status displays without raising validation errors."""
    return load_watchlist_source(settings).entries


def _diagnose_entries(*, source: WatchlistSource, max_instruments: int) -> DiagnosedWatchlist:
    parsed_symbols: list[str] = []
    normalized_symbols: list[str] = []
    invalid_format: list[str] = []
    duplicates: list[str] = []
    non_nse: list[str] = []
    symbols: list[WatchlistSymbol] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for entry in source.entries:
        if entry.count(":") != 1:
            invalid_format.append(entry)
            continue
        exchange_raw, symbol_raw = entry.split(":", 1)
        exchange = exchange_raw.strip().upper()
        tradingsymbol = symbol_raw.strip().upper()
        if not exchange or not tradingsymbol:
            invalid_format.append(entry)
            continue
        key = f"{exchange}:{tradingsymbol}"
        parsed_symbols.append(entry)
        normalized_symbols.append(key)
        if exchange != MVP_EXCHANGE:
            non_nse.append(key)
        if key in seen:
            duplicates.append(key)
        else:
            seen.add(key)
            if exchange == MVP_EXCHANGE:
                symbols.append(WatchlistSymbol(exchange=exchange, tradingsymbol=tradingsymbol))

    if not source.entries:
        errors.append("watchlist_empty")
    if source.blank_entries:
        warnings.append("blank_watchlist_entries_ignored")
    if invalid_format:
        errors.append("watchlist_entries_must_use_exchange_colon_tradingsymbol")
    if duplicates:
        errors.append("duplicate_watchlist_symbol")
    if non_nse:
        errors.append("only_nse_supported_in_current_mvp")
    over_limit = max_instruments < 1 or len(source.entries) > max_instruments
    if max_instruments < 1:
        errors.append("market_data_max_instruments_must_be_positive")
    elif over_limit:
        errors.append("watchlist_exceeds_configured_maximum")

    valid_normalized = sorted(
        {
            symbol.key
            for symbol in symbols
            if symbol.key not in duplicates
        }
    )
    return DiagnosedWatchlist(
        configured_count=len(source.entries),
        parsed_symbols=parsed_symbols,
        normalized_symbols=valid_normalized,
        invalid_format_symbols=invalid_format,
        duplicate_symbols=sorted(set(duplicates)),
        non_nse_symbols=sorted(set(non_nse)),
        over_limit=over_limit,
        symbols=[symbol for symbol in symbols if symbol.key in valid_normalized],
        errors=_unique(errors),
        warnings=_unique(warnings),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
