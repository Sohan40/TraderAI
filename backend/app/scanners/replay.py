"""Deterministic P05 scanner replay CLI over local fixture bars."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.analysis.schemas import CompletedBar
from app.core.config import Settings
from app.scanners.repository import InMemoryScannerRepository
from app.scanners.service import ScannerService


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay deterministic P05 scanner logic.")
    parser.add_argument("--symbol", required=True, help="Symbol such as NSE:SBIN")
    parser.add_argument("--timeframe", default="1minute")
    parser.add_argument("--fixture", required=True, help="JSON fixture of completed candles")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--replay-run-id", default="p05_replay")
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, sort_keys=True))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    bars = _load_fixture(Path(args.fixture), args.symbol, args.timeframe)
    strategies = args.strategy or "opening_range_breakout_long,vwap_pullback_continuation_long"
    service = ScannerService(
        settings=Settings(scanner_enabled=True, scanner_strategies=strategies),
        repository=InMemoryScannerRepository({args.symbol: bars}),
    )
    run = await service.run_replay(
        symbol=args.symbol,
        timeframe=args.timeframe,
        replay_run_id=args.replay_run_id,
    )
    return {
        "evaluated": run.evaluated,
        "inserted": run.inserted,
        "duplicates": run.duplicates,
        "candidates": run.candidates,
        "rejected": run.rejected,
        "veto_counts": run.veto_counts,
        "signals": await service.list_signals(limit=200),
    }


def _load_fixture(path: Path, symbol: str, timeframe: str) -> list[CompletedBar]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    bars: list[CompletedBar] = []
    for index, row in enumerate(rows, start=1):
        bars.append(
            CompletedBar(
                instrument_id=int(row.get("instrument_id", 1)),
                symbol=symbol,
                timeframe=timeframe,
                started_at=_parse_dt(str(row["started_at"])),
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                close_price=Decimal(str(row["close"])),
                volume=int(row.get("volume", index)),
            )
        )
    return bars


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
