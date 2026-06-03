"""Persistence and candle reads for deterministic scanner observations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import desc, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.schemas import CompletedBar
from app.models.schema import candles, instruments, signals
from app.scanners.schemas import LONG, ScannerEvaluation, SignalRecord


class ScannerRepository(Protocol):
    """Scanner storage boundary."""

    async def load_symbols(self) -> list[str]:
        """Return active NSE symbols with stored instruments."""

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CompletedBar]:
        """Load completed stored candles for a symbol."""

    async def insert_signal(self, evaluation: ScannerEvaluation) -> bool:
        """Insert immutable signal; return False when duplicate."""

    async def list_signals(self, *, limit: int) -> list[SignalRecord]:
        """List recent signal observations."""


class SQLAlchemyScannerRepository:
    """SQLAlchemy scanner repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_symbols(self) -> list[str]:
        result = await self._session.execute(
            select(instruments.c.exchange, instruments.c.tradingsymbol)
            .where(instruments.c.exchange == "NSE", instruments.c.is_active.is_(True))
            .order_by(instruments.c.tradingsymbol)
        )
        return [f"{row.exchange}:{row.tradingsymbol}" for row in result]

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CompletedBar]:
        exchange, tradingsymbol = symbol.split(":", 1)
        query = (
            select(
                instruments.c.id,
                instruments.c.exchange,
                instruments.c.tradingsymbol,
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
        if start is not None:
            query = query.where(candles.c.started_at >= start)
        if end is not None:
            query = query.where(candles.c.started_at <= end)
        rows = (await self._session.execute(query)).mappings().all()
        bars = [
            CompletedBar(
                instrument_id=int(row["id"]),
                symbol=f"{row['exchange']}:{row['tradingsymbol']}",
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
        return list(reversed(bars))

    async def insert_signal(self, evaluation: ScannerEvaluation) -> bool:
        try:
            await self._session.execute(
                insert(signals).values(
                    instrument_id=evaluation.instrument_id,
                    strategy_name=evaluation.strategy_name,
                    strategy_version=evaluation.snapshot.strategy_version,
                    signal_key=evaluation.signal_key,
                    signal_status=evaluation.status,
                    signal_time=evaluation.signal_time,
                    direction=LONG,
                    veto_reasons=evaluation.veto_reasons,
                    replay_run_id=evaluation.replay_run_id,
                    features=evaluation.snapshot.as_dict(),
                )
            )
            await self._session.commit()
            return True
        except IntegrityError:
            await self._session.rollback()
            return False

    async def list_signals(self, *, limit: int) -> list[SignalRecord]:
        result = await self._session.execute(
            select(
                signals,
                instruments.c.exchange,
                instruments.c.tradingsymbol,
            )
            .join(instruments, signals.c.instrument_id == instruments.c.id)
            .order_by(desc(signals.c.created_at), desc(signals.c.id))
            .limit(limit)
        )
        output: list[SignalRecord] = []
        for row in result.mappings():
            output.append(
                SignalRecord(
                    id=int(row["id"]),
                    signal_key=str(row["signal_key"]),
                    symbol=f"{row['exchange']}:{row['tradingsymbol']}",
                    strategy_name=str(row["strategy_name"]),
                    strategy_version=str(row["strategy_version"]),
                    signal_status=str(row["signal_status"]),
                    signal_time=row["signal_time"],
                    direction=str(row["direction"]),
                    veto_reasons=list(row["veto_reasons"]),
                    replay_run_id=row["replay_run_id"],
                    features=dict(row["features"]),
                )
            )
        return output


class InMemoryScannerRepository:
    """Deterministic repository for tests and replay fixtures."""

    def __init__(self, bars_by_symbol: dict[str, list[CompletedBar]] | None = None) -> None:
        self.bars_by_symbol = bars_by_symbol or {}
        self.signals: dict[str, ScannerEvaluation] = {}

    async def load_symbols(self) -> list[str]:
        return sorted(self.bars_by_symbol)

    async def load_completed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CompletedBar]:
        bars = [bar for bar in self.bars_by_symbol.get(symbol, []) if bar.timeframe == timeframe]
        if start is not None:
            bars = [bar for bar in bars if bar.started_at >= start]
        if end is not None:
            bars = [bar for bar in bars if bar.started_at <= end]
        return bars[-limit:]

    async def insert_signal(self, evaluation: ScannerEvaluation) -> bool:
        if evaluation.signal_key in self.signals:
            return False
        self.signals[evaluation.signal_key] = evaluation
        return True

    async def list_signals(self, *, limit: int) -> list[SignalRecord]:
        records: list[SignalRecord] = []
        for index, evaluation in enumerate(list(self.signals.values())[-limit:], start=1):
            records.append(
                SignalRecord(
                    id=index,
                    signal_key=evaluation.signal_key,
                    symbol=evaluation.symbol,
                    strategy_name=evaluation.strategy_name,
                    strategy_version=evaluation.snapshot.strategy_version,
                    signal_status=evaluation.status,
                    signal_time=evaluation.signal_time,
                    direction=LONG,
                    veto_reasons=evaluation.veto_reasons,
                    replay_run_id=evaluation.replay_run_id,
                    features=evaluation.snapshot.as_dict(),
                )
            )
        return records
