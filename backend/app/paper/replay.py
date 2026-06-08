"""Deterministic P06 paper replay CLI over stored candles and P05 signals."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from app.core.config import Settings
from app.db.session import async_session_factory
from app.paper.exceptions import PaperError
from app.paper.repository import SQLAlchemyPaperRepository
from app.paper.service import PaperService


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay P06 paper lifecycle from stored data.")
    parser.add_argument("--symbol", required=True, help="Symbol such as NSE:SBIN")
    parser.add_argument("--from", dest="from_time", default=None, help="Inclusive ISO start time")
    parser.add_argument("--to", dest="to_time", default=None, help="Inclusive ISO end time")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--enable-paper",
        action="store_true",
        help="Explicitly run this local CLI invocation with PAPER_ENABLED=true and PAPER_MODE=PAPER.",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings()
    if args.enable_paper:
        settings = Settings(paper_enabled=True, paper_mode="PAPER")
    async with async_session_factory() as session:
        service = PaperService(
            settings=settings,
            repository=SQLAlchemyPaperRepository(session),
        )
        try:
            summary = await service.run_replay(
                symbol=args.symbol,
                start=_parse_dt(args.from_time) if args.from_time else None,
                end=_parse_dt(args.to_time) if args.to_time else None,
                limit=args.limit,
            )
        except PaperError as exc:
            return {
                "paper_enabled": settings.paper_enabled,
                "paper_mode": settings.paper_mode,
                "simulated_only": True,
                "error": exc.__class__.__name__,
                "detail": str(exc),
            }
    return summary.as_dict()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
