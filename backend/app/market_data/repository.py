"""Persistence helpers for P04 read-only market data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.market_data.schemas import CompletedCandle, InstrumentRecord, InstrumentSyncResult, WatchlistSymbol
from app.models.schema import candles, instruments


class MarketDataRepository(Protocol):
    """Storage operations required by P04 services."""

    async def upsert_instruments(
        self,
        broker_instruments: Sequence[Mapping[str, object]],
        watchlist: Sequence[WatchlistSymbol],
    ) -> InstrumentSyncResult:
        """Upsert broker instruments needed by the watchlist."""

    async def resolve_watchlist(
        self,
        watchlist: Sequence[WatchlistSymbol],
    ) -> list[InstrumentRecord]:
        """Resolve configured symbols from local instrument storage."""

    async def save_completed_candles(self, completed: Sequence[CompletedCandle]) -> int:
        """Persist completed candles."""


class SQLAlchemyMarketDataRepository:
    """SQLAlchemy-backed market data repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_instruments(
        self,
        broker_instruments: Sequence[Mapping[str, object]],
        watchlist: Sequence[WatchlistSymbol],
    ) -> InstrumentSyncResult:
        wanted = {(symbol.exchange, symbol.tradingsymbol) for symbol in watchlist}
        fetched = len(broker_instruments)
        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        now = datetime.now(timezone.utc)

        for item in broker_instruments:
            try:
                exchange = str(item.get("exchange", "")).upper()
                tradingsymbol = str(item.get("tradingsymbol", "")).upper()
                if (exchange, tradingsymbol) not in wanted:
                    skipped += 1
                    continue
                token = str(item["instrument_token"])
                values = {
                    "kite_instrument_token": token,
                    "exchange": exchange,
                    "tradingsymbol": tradingsymbol,
                    "name": item.get("name"),
                    "instrument_type": str(item.get("instrument_type", "EQ")),
                    "tick_size": Decimal(str(item.get("tick_size", "0.01"))),
                    "lot_size": int(str(item.get("lot_size", 1))),
                    "is_active": True,
                    "updated_at": now,
                }
                existing = await self._session.execute(
                    select(instruments.c.id).where(
                        instruments.c.exchange == exchange,
                        instruments.c.tradingsymbol == tradingsymbol,
                    )
                )
                row = existing.first()
                if row:
                    await self._session.execute(
                        update(instruments)
                        .where(instruments.c.id == row[0])
                        .values(**values)
                    )
                    updated += 1
                else:
                    await self._session.execute(insert(instruments).values(**values))
                    inserted += 1
            except Exception:
                failed += 1

        await self._session.commit()
        return InstrumentSyncResult(
            fetched=fetched,
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            failed=failed,
        )

    async def resolve_watchlist(
        self,
        watchlist: Sequence[WatchlistSymbol],
    ) -> list[InstrumentRecord]:
        records: list[InstrumentRecord] = []
        for symbol in watchlist:
            result = await self._session.execute(
                select(instruments).where(
                    instruments.c.exchange == symbol.exchange,
                    instruments.c.tradingsymbol == symbol.tradingsymbol,
                    instruments.c.is_active.is_(True),
                )
            )
            row = result.mappings().first()
            if row:
                records.append(
                    InstrumentRecord(
                        id=int(row["id"]),
                        exchange=str(row["exchange"]),
                        tradingsymbol=str(row["tradingsymbol"]),
                        instrument_token=int(row["kite_instrument_token"]),
                        tick_size=Decimal(str(row["tick_size"])),
                        is_active=bool(row["is_active"]),
                    )
                )
        return records

    async def save_completed_candles(self, completed: Sequence[CompletedCandle]) -> int:
        saved = 0
        for candle in completed:
            values = {
                "instrument_id": candle.instrument_id,
                "timeframe": candle.timeframe,
                "started_at": candle.started_at,
                "open_price": candle.open_price,
                "high_price": candle.high_price,
                "low_price": candle.low_price,
                "close_price": candle.close_price,
                "volume": candle.volume,
                "source": candle.source,
            }
            existing = await self._session.execute(
                select(candles.c.id).where(
                    candles.c.instrument_id == candle.instrument_id,
                    candles.c.timeframe == candle.timeframe,
                    candles.c.started_at == candle.started_at,
                )
            )
            row = existing.first()
            if row:
                await self._session.execute(update(candles).where(candles.c.id == row[0]).values(**values))
            else:
                await self._session.execute(insert(candles).values(**values))
            saved += 1

        if saved:
            await self._session.commit()
        return saved


class SessionFactoryMarketDataRepository:
    """Repository that opens a fresh AsyncSession for stream callbacks."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_instruments(
        self,
        broker_instruments: Sequence[Mapping[str, object]],
        watchlist: Sequence[WatchlistSymbol],
    ) -> InstrumentSyncResult:
        async with self._session_factory() as session:
            return await SQLAlchemyMarketDataRepository(session).upsert_instruments(
                broker_instruments,
                watchlist,
            )

    async def resolve_watchlist(
        self,
        watchlist: Sequence[WatchlistSymbol],
    ) -> list[InstrumentRecord]:
        async with self._session_factory() as session:
            return await SQLAlchemyMarketDataRepository(session).resolve_watchlist(watchlist)

    async def save_completed_candles(self, completed: Sequence[CompletedCandle]) -> int:
        async with self._session_factory() as session:
            return await SQLAlchemyMarketDataRepository(session).save_completed_candles(completed)
