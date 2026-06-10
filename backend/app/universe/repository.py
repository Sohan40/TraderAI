"""Persistence and completed-candle reads for universe selection."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import desc, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.schemas import CompletedBar
from app.market_data.schemas import InstrumentRecord
from app.models.schema import candles, instruments, universe_selection_runs
from app.universe.schemas import UniverseSelectionRun


class UniverseRepository(Protocol):
    async def inspect_instruments(self, symbols: Sequence[str]) -> list[InstrumentRecord]: ...

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[CompletedBar]: ...

    async def save_run(self, run: UniverseSelectionRun) -> None: ...

    async def latest_run(self) -> UniverseSelectionRun | None: ...

    async def list_runs(self, *, limit: int) -> list[UniverseSelectionRun]: ...

    async def get_run(self, run_id: str) -> UniverseSelectionRun | None: ...


class SQLAlchemyUniverseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inspect_instruments(self, symbols: Sequence[str]) -> list[InstrumentRecord]:
        output: list[InstrumentRecord] = []
        for symbol in symbols:
            exchange, tradingsymbol = symbol.split(":", 1)
            row = (
                await self._session.execute(
                    select(instruments).where(
                        instruments.c.exchange == exchange,
                        instruments.c.tradingsymbol == tradingsymbol,
                    )
                )
            ).mappings().first()
            if row:
                output.append(
                    InstrumentRecord(
                        id=int(row["id"]),
                        exchange=str(row["exchange"]),
                        tradingsymbol=str(row["tradingsymbol"]),
                        instrument_token=int(row["kite_instrument_token"]),
                        tick_size=Decimal(str(row["tick_size"])),
                        is_active=bool(row["is_active"]),
                    )
                )
        return output

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[CompletedBar]:
        exchange, tradingsymbol = symbol.split(":", 1)
        rows = (
            await self._session.execute(
                select(
                    instruments.c.id,
                    candles.c.timeframe,
                    candles.c.started_at,
                    candles.c.open_price,
                    candles.c.high_price,
                    candles.c.low_price,
                    candles.c.close_price,
                    candles.c.volume,
                )
                .join(instruments, candles.c.instrument_id == instruments.c.id)
                .where(
                    instruments.c.exchange == exchange,
                    instruments.c.tradingsymbol == tradingsymbol,
                    candles.c.timeframe == timeframe,
                )
                .order_by(desc(candles.c.started_at))
                .limit(limit)
            )
        ).mappings().all()
        return list(
            reversed(
                [
                    CompletedBar(
                        instrument_id=int(row["id"]),
                        symbol=symbol,
                        timeframe=str(row["timeframe"]),
                        started_at=row["started_at"],
                        open_price=Decimal(str(row["open_price"])),
                        high_price=Decimal(str(row["high_price"])),
                        low_price=Decimal(str(row["low_price"])),
                        close_price=Decimal(str(row["close_price"])),
                        volume=int(row["volume"]),
                    )
                    for row in rows
                ]
            )
        )

    async def save_run(self, run: UniverseSelectionRun) -> None:
        await self._session.execute(
            insert(universe_selection_runs).values(
                run_id=run.run_id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                timeframe=run.timeframe,
                pool_count=run.pool_count,
                scored_count=run.scored_count,
                selected_count=run.selected_count,
                selected_symbols=run.selected_symbols,
                ranked_symbols=run.ranked_symbols,
                excluded_symbols=run.excluded_symbols,
                config_snapshot=run.config_snapshot,
                warnings=run.warnings,
                errors=run.errors,
            )
        )
        await self._session.commit()

    async def latest_run(self) -> UniverseSelectionRun | None:
        row = (
            await self._session.execute(
                select(universe_selection_runs)
                .order_by(
                    desc(universe_selection_runs.c.created_at),
                    desc(universe_selection_runs.c.id),
                )
                .limit(1)
            )
        ).mappings().first()
        return _run_from_row(row) if row else None

    async def list_runs(self, *, limit: int) -> list[UniverseSelectionRun]:
        rows = (
            await self._session.execute(
                select(universe_selection_runs)
                .order_by(
                    desc(universe_selection_runs.c.created_at),
                    desc(universe_selection_runs.c.id),
                )
                .limit(limit)
            )
        ).mappings().all()
        return [_run_from_row(row) for row in rows]

    async def get_run(self, run_id: str) -> UniverseSelectionRun | None:
        row = (
            await self._session.execute(
                select(universe_selection_runs).where(
                    universe_selection_runs.c.run_id == run_id
                )
            )
        ).mappings().first()
        return _run_from_row(row) if row else None


class SessionFactoryUniverseRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def inspect_instruments(self, symbols: Sequence[str]) -> list[InstrumentRecord]:
        async with self._session_factory() as session:
            return await SQLAlchemyUniverseRepository(session).inspect_instruments(symbols)

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[CompletedBar]:
        async with self._session_factory() as session:
            return await SQLAlchemyUniverseRepository(session).load_completed_bars(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
            )

    async def save_run(self, run: UniverseSelectionRun) -> None:
        async with self._session_factory() as session:
            await SQLAlchemyUniverseRepository(session).save_run(run)

    async def latest_run(self) -> UniverseSelectionRun | None:
        async with self._session_factory() as session:
            return await SQLAlchemyUniverseRepository(session).latest_run()

    async def list_runs(self, *, limit: int) -> list[UniverseSelectionRun]:
        async with self._session_factory() as session:
            return await SQLAlchemyUniverseRepository(session).list_runs(limit=limit)

    async def get_run(self, run_id: str) -> UniverseSelectionRun | None:
        async with self._session_factory() as session:
            return await SQLAlchemyUniverseRepository(session).get_run(run_id)


def _run_from_row(mapping: Any) -> UniverseSelectionRun:
    return UniverseSelectionRun(
        run_id=str(mapping["run_id"]),
        started_at=mapping["started_at"],
        finished_at=mapping["finished_at"],
        enabled=True,
        timeframe=str(mapping["timeframe"]),
        pool_count=int(mapping["pool_count"]),
        scored_count=int(mapping["scored_count"]),
        selected_count=int(mapping["selected_count"]),
        selected_symbols=list(mapping["selected_symbols"]),
        ranked_symbols=list(mapping["ranked_symbols"]),
        excluded_symbols=list(mapping["excluded_symbols"]),
        config_snapshot=dict(mapping["config_snapshot"]),
        warnings=list(mapping["warnings"]),
        errors=list(mapping["errors"]),
    )
