"""Persistence boundary for deterministic paper trading."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import desc, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators import IST
from app.analysis.schemas import CompletedBar
from app.models.schema import candles, instruments, journal_entries, order_events, orders, signals, trades
from app.paper.schemas import (
    PAPER_ENTRY_FILLED,
    PAPER_ENTRY_ORDER_TYPE,
    PAPER_ENTRY_SUBMITTED,
    PAPER_EXIT_FILLED,
    PAPER_EXIT_ORDER_TYPE,
    PAPER_REJECTION_ENTRY_TYPE,
    PAPER_TIMEFRAME,
    PAPER_TRADE_CLOSED,
    PAPER_TRADE_DATA_ENDED,
    PAPER_TRADE_ENTRY_TYPE,
    PAPER_TRADE_NO_FILL,
    PaperExitReason,
    PaperSignal,
    PaperSimulationResult,
)
from app.scanners.schemas import CANDIDATE


class PaperRepository(Protocol):
    """Storage operations needed by P06."""

    async def load_candidate_signals(
        self,
        *,
        symbol: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[PaperSignal]:
        """Load persisted P05 candidates only."""

    async def load_candles(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[CompletedBar]:
        """Load completed one-minute candles for paper replay."""

    async def paper_trade_exists(self, *, signal_id: int) -> bool:
        """Return whether a simulated trade row already exists for the signal."""

    async def count_paper_trades_for_day(self, *, signal_time: datetime) -> int:
        """Count simulated paper trades for the IST session date."""

    async def record_paper_outcome(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
    ) -> None:
        """Persist simulated orders/events/trade rows and journal payload."""

    async def list_journal_outcomes(self, *, limit: int) -> list[dict[str, object]]:
        """Return recent paper journal payloads."""


class DuplicatePaperTradeError(Exception):
    """Raised when the DB uniqueness guard catches a duplicate paper trade."""


class SQLAlchemyPaperRepository:
    """SQLAlchemy implementation for persisted P06 replay."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_candidate_signals(
        self,
        *,
        symbol: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[PaperSignal]:
        query = (
            select(signals, instruments.c.exchange, instruments.c.tradingsymbol)
            .join(instruments, signals.c.instrument_id == instruments.c.id)
            .where(signals.c.signal_status == CANDIDATE)
            .order_by(signals.c.signal_time, signals.c.id)
            .limit(limit)
        )
        if symbol is not None:
            exchange, tradingsymbol = symbol.split(":", 1)
            query = query.where(
                instruments.c.exchange == exchange,
                instruments.c.tradingsymbol == tradingsymbol,
            )
        if start is not None:
            query = query.where(signals.c.signal_time >= start)
        if end is not None:
            query = query.where(signals.c.signal_time <= end)
        rows = (await self._session.execute(query)).mappings().all()
        return [_paper_signal_from_row(row) for row in rows]

    async def load_candles(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
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
                candles.c.timeframe == PAPER_TIMEFRAME,
                candles.c.started_at >= start,
                candles.c.started_at <= end,
            )
            .order_by(candles.c.started_at)
            .limit(limit)
        )
        rows = (await self._session.execute(query)).mappings().all()
        return [
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

    async def paper_trade_exists(self, *, signal_id: int) -> bool:
        result = await self._session.execute(
            select(trades.c.id)
            .where(trades.c.signal_id == signal_id, trades.c.simulated.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count_paper_trades_for_day(self, *, signal_time: datetime) -> int:
        start, end = _ist_day_bounds(signal_time)
        result = await self._session.execute(
            select(trades.c.id)
            .join(signals, trades.c.signal_id == signals.c.id)
            .where(
                trades.c.simulated.is_(True),
                signals.c.signal_time >= start,
                signals.c.signal_time < end,
            )
        )
        return len(result.all())

    async def record_paper_outcome(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
    ) -> None:
        try:
            trade_id: int | None = None
            if outcome.trade_created:
                entry_order_id = await self._insert_entry_order(signal=signal, outcome=outcome)
                exit_order_id = await self._insert_exit_order(
                    signal=signal,
                    outcome=outcome,
                )
                trade_id = await self._insert_trade(
                    signal=signal,
                    outcome=outcome,
                    entry_order_id=entry_order_id,
                    exit_order_id=exit_order_id,
                )
            await self._insert_journal(signal=signal, outcome=outcome, trade_id=trade_id)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicatePaperTradeError("paper trade already exists for signal") from exc

    async def list_journal_outcomes(self, *, limit: int) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(journal_entries.c.payload)
            .where(
                journal_entries.c.entry_type.in_(
                    [PAPER_TRADE_ENTRY_TYPE, PAPER_REJECTION_ENTRY_TYPE]
                )
            )
            .order_by(desc(journal_entries.c.created_at), desc(journal_entries.c.id))
            .limit(limit)
        )
        return [dict(row[0]) for row in result.all()]

    async def _insert_entry_order(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
    ) -> int:
        order_id = (
            await self._session.execute(
                insert(orders)
                .values(
                    signal_id=signal.id,
                    simulated=True,
                    instrument_id=signal.instrument_id,
                    side="BUY",
                    order_type=PAPER_ENTRY_ORDER_TYPE,
                    quantity=outcome.quantity,
                    limit_price=outcome.entry_reference_price,
                    status=outcome.entry_order_status,
                )
                .returning(orders.c.id)
            )
        ).scalar_one()
        await self._session.execute(
            insert(order_events).values(
                order_id=order_id,
                event_type=PAPER_ENTRY_SUBMITTED,
                broker_status=None,
                payload=_event_payload(outcome, event_type=PAPER_ENTRY_SUBMITTED),
            )
        )
        await self._session.execute(
            insert(order_events).values(
                order_id=order_id,
                event_type=outcome.entry_order_status,
                broker_status=None,
                payload=_event_payload(outcome, event_type=outcome.entry_order_status),
            )
        )
        return int(order_id)

    async def _insert_exit_order(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
    ) -> int | None:
        if outcome.entry_order_status != PAPER_ENTRY_FILLED or outcome.exit_price is None:
            return None
        order_id = (
            await self._session.execute(
                insert(orders)
                .values(
                    signal_id=signal.id,
                    simulated=True,
                    instrument_id=signal.instrument_id,
                    side="SELL",
                    order_type=PAPER_EXIT_ORDER_TYPE,
                    quantity=outcome.quantity,
                    limit_price=outcome.exit_price,
                    status=PAPER_EXIT_FILLED,
                )
                .returning(orders.c.id)
            )
        ).scalar_one()
        await self._session.execute(
            insert(order_events).values(
                order_id=order_id,
                event_type=PAPER_EXIT_FILLED,
                broker_status=None,
                payload=_event_payload(outcome, event_type=PAPER_EXIT_FILLED),
            )
        )
        return int(order_id)

    async def _insert_trade(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
        entry_order_id: int,
        exit_order_id: int | None,
    ) -> int:
        status = _trade_status(outcome)
        trade_id = (
            await self._session.execute(
                insert(trades)
                .values(
                    signal_id=signal.id,
                    simulated=True,
                    entry_order_id=entry_order_id,
                    exit_order_id=exit_order_id,
                    instrument_id=signal.instrument_id,
                    quantity=outcome.quantity,
                    entry_price=outcome.entry_fill_price,
                    exit_price=outcome.exit_price,
                    realized_pnl=outcome.net_estimated_pnl,
                    gross_pnl=outcome.gross_pnl,
                    estimated_costs=outcome.estimated_costs,
                    net_pnl=outcome.net_estimated_pnl,
                    exit_reason=outcome.exit_reason.value,
                    paper_mode=outcome.paper_mode.value,
                    opened_at=outcome.entry_fill_time,
                    closed_at=outcome.exit_time,
                    status=status,
                )
                .returning(trades.c.id)
            )
        ).scalar_one()
        return int(trade_id)

    async def _insert_journal(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
        trade_id: int | None,
    ) -> None:
        entry_type = PAPER_TRADE_ENTRY_TYPE if outcome.trade_created else PAPER_REJECTION_ENTRY_TYPE
        subject_type = "trade" if trade_id is not None else "signal"
        subject_id = trade_id if trade_id is not None else signal.id
        payload = outcome.as_payload()
        payload["signal_time"] = signal.signal_time.isoformat()
        payload["strategy_version"] = signal.strategy_version
        await self._session.execute(
            insert(journal_entries).values(
                entry_type=entry_type,
                subject_type=subject_type,
                subject_id=subject_id,
                message=(
                    f"Paper outcome {outcome.exit_reason.value} for "
                    f"{signal.symbol} {signal.signal_key}"
                ),
                payload=payload,
            )
        )


class InMemoryPaperRepository:
    """Deterministic repository for unit tests."""

    def __init__(
        self,
        *,
        signals: Sequence[PaperSignal] | None = None,
        candles_by_symbol: dict[str, list[CompletedBar]] | None = None,
    ) -> None:
        self.signals = list(signals or [])
        self.candles_by_symbol = candles_by_symbol or {}
        self.orders: list[dict[str, object]] = []
        self.order_events: list[dict[str, object]] = []
        self.trades: list[dict[str, object]] = []
        self.journal: list[dict[str, object]] = []

    async def load_candidate_signals(
        self,
        *,
        symbol: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[PaperSignal]:
        loaded = [signal for signal in self.signals if signal.signal_status == CANDIDATE]
        if symbol is not None:
            loaded = [signal for signal in loaded if signal.symbol == symbol]
        if start is not None:
            loaded = [signal for signal in loaded if signal.signal_time >= start]
        if end is not None:
            loaded = [signal for signal in loaded if signal.signal_time <= end]
        return sorted(loaded, key=lambda signal: (signal.signal_time, signal.id))[:limit]

    async def load_candles(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[CompletedBar]:
        loaded = [
            candle
            for candle in self.candles_by_symbol.get(symbol, [])
            if candle.timeframe == PAPER_TIMEFRAME and start <= candle.started_at <= end
        ]
        return sorted(loaded, key=lambda candle: candle.started_at)[:limit]

    async def paper_trade_exists(self, *, signal_id: int) -> bool:
        return any(trade["signal_id"] == signal_id and trade["simulated"] for trade in self.trades)

    async def count_paper_trades_for_day(self, *, signal_time: datetime) -> int:
        signal_ids = {
            signal.id
            for signal in self.signals
            if signal.signal_time.astimezone(IST).date() == signal_time.astimezone(IST).date()
        }
        return sum(1 for trade in self.trades if trade["signal_id"] in signal_ids)

    async def record_paper_outcome(
        self,
        *,
        signal: PaperSignal,
        outcome: PaperSimulationResult,
    ) -> None:
        if outcome.trade_created and await self.paper_trade_exists(signal_id=signal.id):
            raise DuplicatePaperTradeError("paper trade already exists for signal")
        if outcome.trade_created:
            entry_order_id = len(self.orders) + 1
            self.orders.append(
                {
                    "id": entry_order_id,
                    "signal_id": signal.id,
                    "simulated": True,
                    "side": "BUY",
                    "order_type": PAPER_ENTRY_ORDER_TYPE,
                    "quantity": outcome.quantity,
                    "limit_price": outcome.entry_reference_price,
                    "status": outcome.entry_order_status,
                }
            )
            self.order_events.append(
                {
                    "order_id": entry_order_id,
                    "event_type": outcome.entry_order_status,
                    "payload": _event_payload(outcome, event_type=outcome.entry_order_status),
                }
            )
            exit_order_id = None
            if outcome.entry_order_status == PAPER_ENTRY_FILLED and outcome.exit_price is not None:
                exit_order_id = len(self.orders) + 1
                self.orders.append(
                    {
                        "id": exit_order_id,
                        "signal_id": signal.id,
                        "simulated": True,
                        "side": "SELL",
                        "order_type": PAPER_EXIT_ORDER_TYPE,
                        "quantity": outcome.quantity,
                        "limit_price": outcome.exit_price,
                        "status": PAPER_EXIT_FILLED,
                    }
                )
                self.order_events.append(
                    {
                        "order_id": exit_order_id,
                        "event_type": PAPER_EXIT_FILLED,
                        "payload": _event_payload(outcome, event_type=PAPER_EXIT_FILLED),
                    }
                )
            self.trades.append(
                {
                    "id": len(self.trades) + 1,
                    "signal_id": signal.id,
                    "simulated": True,
                    "entry_order_id": entry_order_id,
                    "exit_order_id": exit_order_id,
                    "quantity": outcome.quantity,
                    "entry_price": outcome.entry_fill_price,
                    "exit_price": outcome.exit_price,
                    "exit_reason": outcome.exit_reason.value,
                    "gross_pnl": outcome.gross_pnl,
                    "estimated_costs": outcome.estimated_costs,
                    "net_pnl": outcome.net_estimated_pnl,
                    "paper_mode": outcome.paper_mode.value,
                    "status": _trade_status(outcome),
                }
            )
        payload = outcome.as_payload()
        payload["signal_time"] = signal.signal_time.isoformat()
        payload["strategy_version"] = signal.strategy_version
        self.journal.append(payload)

    async def list_journal_outcomes(self, *, limit: int) -> list[dict[str, object]]:
        return list(reversed(self.journal[-limit:]))


def _paper_signal_from_row(row: Any) -> PaperSignal:
    mapping: dict[str, Any] = dict(row)
    return PaperSignal(
        id=int(mapping["id"]),
        instrument_id=int(mapping["instrument_id"]),
        signal_key=str(mapping["signal_key"]),
        symbol=f"{mapping['exchange']}:{mapping['tradingsymbol']}",
        strategy_name=str(mapping["strategy_name"]),
        strategy_version=str(mapping["strategy_version"]),
        signal_status=str(mapping["signal_status"]),
        signal_time=mapping["signal_time"],
        direction=str(mapping["direction"]),
        veto_reasons=list(mapping["veto_reasons"]),
        replay_run_id=mapping["replay_run_id"],
        features=dict(mapping["features"]),
    )


def _event_payload(outcome: PaperSimulationResult, *, event_type: str) -> dict[str, object]:
    payload = outcome.as_payload()
    payload["event_type"] = event_type
    payload["broker_order_id"] = None
    return payload


def _trade_status(outcome: PaperSimulationResult) -> str:
    if outcome.exit_reason == PaperExitReason.NO_FILL:
        return PAPER_TRADE_NO_FILL
    if outcome.exit_reason == PaperExitReason.DATA_ENDED:
        return PAPER_TRADE_DATA_ENDED
    return PAPER_TRADE_CLOSED


def _ist_day_bounds(value: datetime) -> tuple[datetime, datetime]:
    session_date = value.astimezone(IST).date()
    start_ist = datetime.combine(session_date, time.min, tzinfo=IST)
    end_ist = start_ist + timedelta(days=1)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)
