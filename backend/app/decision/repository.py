"""Persistence boundary for P07 model runs and recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import and_, desc, exists, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.decision.schemas import DecisionOutput, DecisionSignal, PersistedDecision
from app.models.schema import instruments, model_runs, recommendations, signals
from app.scanners.schemas import CANDIDATE


class DecisionRepository(Protocol):
    async def load_signal(self, *, signal_id: int) -> DecisionSignal | None: ...
    async def find_by_evaluation_key(self, *, evaluation_key: str) -> PersistedDecision | None: ...
    async def record(
        self,
        *,
        signal: DecisionSignal,
        adapter: str,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        input_payload: dict[str, object],
        output: DecisionOutput,
        output_payload: dict[str, object],
        status: str,
        request_id: str | None,
        latency_ms: int | None,
        error_code: str | None,
        evaluation_key: str | None,
    ) -> PersistedDecision: ...
    async def list_recommendations(self, *, limit: int) -> list[PersistedDecision]: ...
    async def latest_for_signal_ids(
        self,
        *,
        signal_ids: list[int],
    ) -> dict[int, dict[str, object]]: ...
    async def list_unevaluated_candidate_ids(
        self,
        *,
        adapter: str,
        model_name: str,
        prompt_version: str,
        evaluation_mode: str,
        limit: int,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        symbols: list[str] | None = None,
        oldest_first: bool = True,
    ) -> list[int]: ...


class SQLAlchemyDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_signal(self, *, signal_id: int) -> DecisionSignal | None:
        row = (
            await self._session.execute(
                select(signals, instruments.c.exchange, instruments.c.tradingsymbol)
                .join(instruments, signals.c.instrument_id == instruments.c.id)
                .where(signals.c.id == signal_id)
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        return _signal_from_row(row)

    async def find_by_evaluation_key(self, *, evaluation_key: str) -> PersistedDecision | None:
        row = (
            await self._session.execute(
                _recommendation_query().where(recommendations.c.evaluation_key == evaluation_key)
            )
        ).mappings().one_or_none()
        return None if row is None else _persisted_from_row(row, existing=True)

    async def record(
        self,
        *,
        signal: DecisionSignal,
        adapter: str,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        input_payload: dict[str, object],
        output: DecisionOutput,
        output_payload: dict[str, object],
        status: str,
        request_id: str | None,
        latency_ms: int | None,
        error_code: str | None,
        evaluation_key: str | None,
    ) -> PersistedDecision:
        try:
            model_run_id = int(
                (
                    await self._session.execute(
                        insert(model_runs)
                        .values(
                            provider="openai" if adapter == "openai" else "fake",
                            adapter=adapter,
                            model_name=model_name,
                            request_id=request_id,
                            prompt_version=prompt_version,
                            input_hash=input_hash,
                            input_payload=input_payload,
                            output_payload=output_payload,
                            latency_ms=latency_ms,
                            error_code=error_code,
                            status=status,
                        )
                        .returning(model_runs.c.id)
                    )
                ).scalar_one()
            )
            recommendation_id = int(
                (
                    await self._session.execute(
                        insert(recommendations)
                        .values(
                            signal_id=signal.id,
                            model_run_id=model_run_id,
                            verdict=output.verdict.value,
                            confidence=Decimal(str(output.confidence)),
                            warnings=output.warnings,
                            evaluation_key=evaluation_key,
                            rationale="\n".join(output.reasons),
                            payload=output.model_dump(mode="json"),
                        )
                        .returning(recommendations.c.id)
                    )
                ).scalar_one()
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if evaluation_key is not None:
                existing = await self.find_by_evaluation_key(evaluation_key=evaluation_key)
                if existing is not None:
                    return existing
            raise
        row = (
            await self._session.execute(
                _recommendation_query().where(recommendations.c.id == recommendation_id)
            )
        ).mappings().one()
        return _persisted_from_row(row)

    async def list_recommendations(self, *, limit: int) -> list[PersistedDecision]:
        rows = (
            await self._session.execute(
                _recommendation_query()
                .order_by(desc(recommendations.c.created_at), desc(recommendations.c.id))
                .limit(limit)
            )
        ).mappings()
        return [_persisted_from_row(row) for row in rows]

    async def latest_for_signal_ids(
        self,
        *,
        signal_ids: list[int],
    ) -> dict[int, dict[str, object]]:
        if not signal_ids:
            return {}
        rows = (
            await self._session.execute(
                _recommendation_query()
                .where(recommendations.c.signal_id.in_(signal_ids))
                .order_by(
                    recommendations.c.signal_id,
                    desc(recommendations.c.created_at),
                    desc(recommendations.c.id),
                )
            )
        ).mappings()
        output: dict[int, dict[str, object]] = {}
        for row in rows:
            signal_id = int(row["signal_id"])
            if signal_id not in output:
                output[signal_id] = _comparison_from_row(row)
        return output

    async def list_unevaluated_candidate_ids(
        self,
        *,
        adapter: str,
        model_name: str,
        prompt_version: str,
        evaluation_mode: str,
        limit: int,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        symbols: list[str] | None = None,
        oldest_first: bool = True,
    ) -> list[int]:
        evaluated = (
            select(recommendations.c.id)
            .join(model_runs, recommendations.c.model_run_id == model_runs.c.id)
            .where(
                recommendations.c.signal_id == signals.c.id,
                model_runs.c.adapter == adapter,
                model_runs.c.model_name == model_name,
                model_runs.c.prompt_version == prompt_version,
                model_runs.c.input_payload["evaluation_mode"].astext == evaluation_mode,
            )
        )
        query = (
            select(signals.c.id)
            .join(instruments, signals.c.instrument_id == instruments.c.id)
            .where(signals.c.signal_status == CANDIDATE, ~exists(evaluated))
        )
        if started_at is not None:
            query = query.where(signals.c.created_at >= started_at)
        if finished_at is not None:
            query = query.where(signals.c.created_at <= finished_at)
        if symbols:
            symbol_conditions = []
            for symbol in symbols:
                exchange, tradingsymbol = symbol.split(":", 1)
                symbol_conditions.append(
                    and_(
                        instruments.c.exchange == exchange,
                        instruments.c.tradingsymbol == tradingsymbol,
                    )
                )
            query = query.where(or_(*symbol_conditions))
        ordering = signals.c.created_at.asc() if oldest_first else signals.c.created_at.desc()
        rows = await self._session.execute(
            query.order_by(ordering, signals.c.id.asc()).limit(limit)
        )
        return [int(row.id) for row in rows]


class InMemoryDecisionRepository:
    def __init__(self, *, signals: list[DecisionSignal] | None = None) -> None:
        self.signals = {signal.id: signal for signal in signals or []}
        self.recommendations: list[PersistedDecision] = []
        self.model_runs: list[dict[str, object]] = []
        self.evaluation_keys: dict[str, PersistedDecision] = {}

    async def load_signal(self, *, signal_id: int) -> DecisionSignal | None:
        return self.signals.get(signal_id)

    async def find_by_evaluation_key(self, *, evaluation_key: str) -> PersistedDecision | None:
        found = self.evaluation_keys.get(evaluation_key)
        return None if found is None else PersistedDecision(**{**found.__dict__, "existing": True})

    async def record(
        self,
        *,
        signal: DecisionSignal,
        adapter: str,
        model_name: str,
        prompt_version: str,
        input_hash: str,
        input_payload: dict[str, object],
        output: DecisionOutput,
        output_payload: dict[str, object],
        status: str,
        request_id: str | None,
        latency_ms: int | None,
        error_code: str | None,
        evaluation_key: str | None,
    ) -> PersistedDecision:
        model_run_id = len(self.model_runs) + 1
        self.model_runs.append(
            {
                "id": model_run_id,
                "adapter": adapter,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "input_hash": input_hash,
                "input_payload": input_payload,
                "output_payload": output_payload,
                "status": status,
                "error_code": error_code,
                "request_id": request_id,
                "latency_ms": latency_ms,
            }
        )
        persisted = PersistedDecision(
            recommendation_id=len(self.recommendations) + 1,
            model_run_id=model_run_id,
            signal_id=signal.id,
            signal_key=signal.signal_key,
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            verdict=output.verdict.value,
            confidence=output.confidence,
            reasons=list(output.reasons),
            warnings=list(output.warnings),
            data_sufficiency=output.data_sufficiency.value,
            adapter=adapter,
            model_name=model_name,
            prompt_version=prompt_version,
            status=status,
            error_code=error_code,
            signal_time=signal.signal_time,
            created_at=datetime.now(timezone.utc),
        )
        self.recommendations.append(persisted)
        if evaluation_key is not None:
            self.evaluation_keys[evaluation_key] = persisted
        return persisted

    async def list_recommendations(self, *, limit: int) -> list[PersistedDecision]:
        return list(reversed(self.recommendations[-limit:]))

    async def latest_for_signal_ids(
        self,
        *,
        signal_ids: list[int],
    ) -> dict[int, dict[str, object]]:
        requested = set(signal_ids)
        output: dict[int, dict[str, object]] = {}
        for item in reversed(self.recommendations):
            if item.signal_id in requested and item.signal_id not in output:
                output[item.signal_id] = {
                    "verdict": item.verdict,
                    "confidence": item.confidence,
                    "warnings": item.warnings,
                    "recommendation_id": item.recommendation_id,
                    "prompt_version": item.prompt_version,
                }
        return output

    async def list_unevaluated_candidate_ids(
        self,
        *,
        adapter: str,
        model_name: str,
        prompt_version: str,
        evaluation_mode: str,
        limit: int,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        symbols: list[str] | None = None,
        oldest_first: bool = True,
    ) -> list[int]:
        del adapter, model_name, prompt_version, evaluation_mode
        requested_symbols = set(symbols or [])
        candidates = [
            signal
            for signal in self.signals.values()
            if signal.signal_status == CANDIDATE
            and (not requested_symbols or signal.symbol in requested_symbols)
            and (
                started_at is None
                or (signal.created_at or signal.signal_time) >= started_at
            )
            and (
                finished_at is None
                or (signal.created_at or signal.signal_time) <= finished_at
            )
            and not any(item.signal_id == signal.id for item in self.recommendations)
        ]
        candidates.sort(
            key=lambda item: (item.created_at or item.signal_time, item.id),
            reverse=not oldest_first,
        )
        return [item.id for item in candidates[:limit]]


class SessionFactoryDecisionRepository:
    """Open a fresh database session for process-local decision automation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_signal(self, *, signal_id: int) -> DecisionSignal | None:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(session).load_signal(signal_id=signal_id)

    async def find_by_evaluation_key(
        self,
        *,
        evaluation_key: str,
    ) -> PersistedDecision | None:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(session).find_by_evaluation_key(
                evaluation_key=evaluation_key
            )

    async def record(self, **kwargs: Any) -> PersistedDecision:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(session).record(**kwargs)

    async def list_recommendations(self, *, limit: int) -> list[PersistedDecision]:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(session).list_recommendations(limit=limit)

    async def latest_for_signal_ids(
        self,
        *,
        signal_ids: list[int],
    ) -> dict[int, dict[str, object]]:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(session).latest_for_signal_ids(
                signal_ids=signal_ids
            )

    async def list_unevaluated_candidate_ids(self, **kwargs: Any) -> list[int]:
        async with self._session_factory() as session:
            return await SQLAlchemyDecisionRepository(
                session
            ).list_unevaluated_candidate_ids(**kwargs)


def _recommendation_query() -> Any:
    return (
        select(
            recommendations,
            model_runs.c.adapter,
            model_runs.c.model_name,
            model_runs.c.prompt_version,
            model_runs.c.status,
            model_runs.c.error_code,
            signals.c.signal_key,
            signals.c.strategy_name,
            signals.c.signal_time,
            instruments.c.exchange,
            instruments.c.tradingsymbol,
        )
        .join(model_runs, recommendations.c.model_run_id == model_runs.c.id)
        .join(signals, recommendations.c.signal_id == signals.c.id)
        .join(instruments, signals.c.instrument_id == instruments.c.id)
    )


def _signal_from_row(row: Any) -> DecisionSignal:
    return DecisionSignal(
        id=int(row["id"]),
        signal_key=str(row["signal_key"]),
        symbol=f"{row['exchange']}:{row['tradingsymbol']}",
        strategy_name=str(row["strategy_name"]),
        strategy_version=str(row["strategy_version"]),
        signal_status=str(row["signal_status"]),
        signal_time=row["signal_time"],
        features=dict(row["features"]),
        created_at=row["created_at"],
    )


def _persisted_from_row(row: Any, *, existing: bool = False) -> PersistedDecision:
    payload = dict(row["payload"])
    return PersistedDecision(
        recommendation_id=int(row["id"]),
        model_run_id=int(row["model_run_id"]),
        signal_id=int(row["signal_id"]),
        signal_key=str(row["signal_key"]),
        symbol=f"{row['exchange']}:{row['tradingsymbol']}",
        strategy=str(row["strategy_name"]),
        verdict=str(row["verdict"]),
        confidence=float(row["confidence"]),
        reasons=list(payload.get("reasons", [])),
        warnings=list(row["warnings"]),
        data_sufficiency=str(payload.get("data_sufficiency", "INSUFFICIENT")),
        adapter=str(row["adapter"]),
        model_name=str(row["model_name"]),
        prompt_version=str(row["prompt_version"]),
        status=str(row["status"]),
        error_code=row["error_code"],
        signal_time=row["signal_time"],
        created_at=row["created_at"],
        existing=existing,
    )


def _comparison_from_row(row: Any) -> dict[str, object]:
    return {
        "recommendation_id": int(row["id"]),
        "verdict": str(row["verdict"]),
        "confidence": float(row["confidence"]),
        "warnings": list(row["warnings"]),
        "prompt_version": str(row["prompt_version"]),
    }
