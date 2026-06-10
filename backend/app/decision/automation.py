"""Bounded P07 evaluation after persisted scanner candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.analysis.indicators import IST
from app.core.config import Settings
from app.decision.repository import DecisionRepository
from app.decision.schemas import PersistedDecision
from app.decision.service import DecisionService


class DecisionNotifier(Protocol):
    async def notify(
        self,
        *,
        level: str,
        event: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> object: ...


class DecisionAutomationService:
    """Evaluate only bounded, persisted, unevaluated P05 candidates."""

    def __init__(
        self,
        *,
        settings: Settings,
        decision_service: DecisionService,
        repository: DecisionRepository,
        notifier: DecisionNotifier,
    ) -> None:
        self._settings = settings
        self._decision_service = decision_service
        self._repository = repository
        self._notifier = notifier
        self._last_summary: dict[str, object] | None = None

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._settings.market_ops_decision_auto_evaluate_enabled,
            "decision_enabled": self._settings.openai_decision_enabled,
            "candidate_only": self._settings.market_ops_decision_auto_evaluate_only_candidates,
            "max_signals": self._bounded_max(),
            "evaluation_mode": self._settings.openai_decision_evaluation_mode,
            "notify_enabled": self._settings.market_ops_decision_notify_enabled,
            "notify_verdicts": sorted(self._notify_verdicts()),
            "notify_include_reasons": (
                self._settings.market_ops_decision_notify_include_reasons
            ),
            "notify_include_warnings": (
                self._settings.market_ops_decision_notify_include_warnings
            ),
            "last_summary": self._last_summary,
            "paper_report_only": True,
            "live_execution": False,
        }

    async def evaluate_scanner_batch(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        symbols: list[str],
        dry_run: bool,
        candidate_count: int,
    ) -> dict[str, object]:
        reason = self._auto_skip_reason(
            dry_run=dry_run,
            candidate_count=candidate_count,
        )
        if reason is not None:
            summary = self._empty_summary(skipped_reason=reason)
            self._last_summary = summary
            return summary
        summary = await self._evaluate_candidates(
            started_at=started_at,
            finished_at=finished_at,
            symbols=symbols,
            limit=self._bounded_max(),
            oldest_first=True,
            source="scanner_batch",
        )
        self._last_summary = summary
        return summary

    async def evaluate_latest(self, *, limit: int) -> dict[str, object]:
        if not self._settings.openai_decision_enabled:
            from app.decision.exceptions import DecisionDisabledError

            raise DecisionDisabledError("OpenAI decision evaluation is disabled.")
        summary = await self._evaluate_candidates(
            limit=min(max(1, limit), self._bounded_max()),
            oldest_first=False,
            source="manual_latest",
        )
        self._last_summary = summary
        return summary

    async def _evaluate_candidates(
        self,
        *,
        limit: int,
        oldest_first: bool,
        source: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, object]:
        identity = self._decision_service.evaluation_identity()
        signal_ids = await self._repository.list_unevaluated_candidate_ids(
            **identity,
            limit=limit + 1,
            started_at=started_at,
            finished_at=finished_at,
            symbols=symbols,
            oldest_first=oldest_first,
        )
        truncated = len(signal_ids) > limit
        signal_ids = signal_ids[:limit]
        created = existing = failed = notified = 0
        results: list[dict[str, object]] = []
        for signal_id in signal_ids:
            try:
                decision = await self._decision_service.evaluate(
                    signal_id=signal_id,
                    force=False,
                )
            except Exception:
                failed += 1
                await self._notify_failure(signal_id=signal_id)
                results.append(
                    {
                        "signal_id": signal_id,
                        "status": "FAILED",
                        "error_code": "decision_auto_evaluation_failed",
                    }
                )
                continue
            if decision.existing:
                existing += 1
            else:
                created += 1
                if decision.status == "FAILED":
                    failed += 1
                if await self._notify_decision(decision):
                    notified += 1
            results.append(
                {
                    "signal_id": decision.signal_id,
                    "verdict": decision.verdict,
                    "status": decision.status,
                    "error_code": decision.error_code,
                    "existing": decision.existing,
                }
            )
        return {
            "source": source,
            "attempted": len(signal_ids),
            "created": created,
            "existing": existing,
            "failed": failed,
            "skipped": 0,
            "notified": notified,
            "truncated": truncated,
            "results": results,
        }

    async def _notify_decision(self, decision: PersistedDecision) -> bool:
        if not self._settings.market_ops_decision_notify_enabled:
            return False
        failed = decision.status == "FAILED"
        if not failed and decision.verdict not in self._notify_verdicts():
            return False
        verdict_events = {
            "ELIGIBLE": "decision_candidate_eligible",
            "WATCH": "decision_candidate_watch",
            "REJECT": "decision_candidate_rejected",
        }
        event = (
            "decision_auto_evaluation_failed"
            if failed
            else verdict_events[decision.verdict]
        )
        details: dict[str, object] = {
            "signal_id": decision.signal_id,
            "symbol": decision.symbol,
            "strategy": decision.strategy,
            "signal_time_ist": decision.signal_time.astimezone(IST).isoformat(),
            "verdict": decision.verdict,
            "confidence": decision.confidence,
            "data_sufficiency": decision.data_sufficiency,
            "model_name": decision.model_name,
            "prompt_version": decision.prompt_version,
            "newly_created": True,
        }
        if self._settings.market_ops_decision_notify_include_reasons:
            details["reasons"] = decision.reasons[:2]
        if self._settings.market_ops_decision_notify_include_warnings:
            details["warnings"] = decision.warnings[:2]
        result = await self._notifier.notify(
            level="warning" if failed or decision.verdict == "ELIGIBLE" else "info",
            event=event,
            message="A scanner candidate received a new P07 shadow decision.",
            details=details,
        )
        return bool(getattr(result, "ok", False)) and not bool(
            getattr(result, "skipped", False)
        )

    async def _notify_failure(self, *, signal_id: int) -> None:
        if not self._settings.market_ops_decision_notify_enabled:
            return
        await self._notifier.notify(
            level="warning",
            event="decision_auto_evaluation_failed",
            message="Automatic P07 evaluation failed safely.",
            details={"signal_id": signal_id},
        )

    def _auto_skip_reason(self, *, dry_run: bool, candidate_count: int) -> str | None:
        if not self._settings.market_ops_decision_auto_evaluate_enabled:
            return "auto_evaluation_disabled"
        if not self._settings.openai_decision_enabled:
            return "decision_service_disabled"
        if not self._settings.market_ops_decision_auto_evaluate_only_candidates:
            return "candidate_only_required"
        if dry_run:
            return "scanner_dry_run"
        if candidate_count < 1:
            return "no_candidates"
        return None

    def _bounded_max(self) -> int:
        return max(1, min(self._settings.market_ops_decision_auto_evaluate_max_signals, 50))

    def _notify_verdicts(self) -> set[str]:
        allowed = {"ELIGIBLE", "WATCH", "REJECT"}
        configured = {
            item.strip().upper()
            for item in self._settings.market_ops_decision_notify_verdicts.split(",")
            if item.strip()
        }
        return configured & allowed

    @staticmethod
    def _empty_summary(*, skipped_reason: str) -> dict[str, object]:
        return {
            "source": "scanner_batch",
            "attempted": 0,
            "created": 0,
            "existing": 0,
            "failed": 0,
            "skipped": 1,
            "skipped_reason": skipped_reason,
            "notified": 0,
            "truncated": False,
            "results": [],
        }
