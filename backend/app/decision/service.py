"""Operator-triggered P07 structured decision orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from time import perf_counter

from pydantic import ValidationError

from app.analysis.indicators import IST
from app.core.config import Settings
from app.decision.adapter import DecisionAdapter
from app.decision.exceptions import (
    DecisionAdapterError,
    DecisionConfigError,
    DecisionDisabledError,
    DecisionSignalIneligibleError,
    DecisionSignalNotFoundError,
)
from app.decision.repository import DecisionRepository
from app.decision.schemas import (
    DataSufficiency,
    DecisionInput,
    DecisionLimits,
    DecisionOutput,
    DecisionPaperState,
    DecisionSignal,
    DecisionVerdict,
    PersistedDecision,
)
from app.scanners.schemas import CANDIDATE, P05_STRATEGIES

PROHIBITED_KEY_FRAGMENTS = (
    "quantity",
    "order",
    "broker",
    "position_size",
    "risk_override",
    "access_token",
    "api_key",
    "secret",
)
EXTERNAL_FACT_PATTERN = re.compile(
    r"\b(news|earnings|fundamentals?|announcement|macro|fii|dii|institutional flow|"
    r"company results?|web search|external event)\b",
    re.IGNORECASE,
)
ALLOWED_INDICATORS = {
    "ema_9",
    "ema_20",
    "ema_50",
    "rsi_14",
    "atr_14",
    "vwap",
    "opening_range_high",
    "opening_range_low",
    "previous_day_high",
    "previous_day_low",
    "volume_ratio",
    "relative_index_move",
    "spread_pct",
}
ALLOWED_DATA_QUALITY = {
    "history_complete",
    "quote_fresh",
    "spread_available",
    "candle_continuity_ok",
    "session_start_available",
    "opening_range_complete",
    "current_session_complete_through_latest",
}
ALLOWED_FUTURE_QUALIFICATION = {
    "observation_mode",
    "eligible_strategy",
    "spread_required",
    "spread_validated",
    "future_live_qualified",
    "warnings",
}


class DecisionService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DecisionRepository,
        adapter: DecisionAdapter,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._adapter = adapter

    async def status(self) -> dict[str, object]:
        adapter = self._settings.openai_decision_adapter.strip().lower()
        return {
            "enabled": self._settings.openai_decision_enabled,
            "adapter": adapter,
            "model_configured": bool(self._settings.openai_model),
            "api_key_configured": bool(self._settings.openai_api_key),
            "prompt_version": self._settings.openai_decision_prompt_version,
            "store": self._settings.openai_decision_store,
            "min_confidence": self._settings.openai_decision_min_confidence,
            "operator_triggered_only": True,
            "paper_report_only": True,
            "live_execution": False,
        }

    async def evaluate(self, *, signal_id: int, force: bool = False) -> PersistedDecision:
        if not self._settings.openai_decision_enabled:
            raise DecisionDisabledError("OpenAI decision evaluation is disabled.")
        signal = await self._repository.load_signal(signal_id=signal_id)
        if signal is None:
            raise DecisionSignalNotFoundError("Signal not found.")
        if signal.signal_status != CANDIDATE:
            raise DecisionSignalIneligibleError("Only CANDIDATE signals can be evaluated.")
        adapter_name = self._adapter_name()
        model_name = self._model_name(adapter_name)
        evaluation_key = _evaluation_key(
            signal=signal,
            adapter=adapter_name,
            model_name=model_name,
            prompt_version=self._settings.openai_decision_prompt_version,
        )
        if not force:
            existing = await self._repository.find_by_evaluation_key(
                evaluation_key=evaluation_key
            )
            if existing is not None:
                return existing

        started = perf_counter()
        error_code: str | None = None
        request_id: str | None = None
        try:
            decision_input = self._build_input(signal)
            input_payload = decision_input.model_dump(mode="json")
            input_hash = _hash_payload(input_payload)
            adapter_result = await self._adapter.evaluate(decision_input)
            request_id = adapter_result.request_id
            output, error_code = self._validate_output(
                adapter_result.output,
                signal=signal,
            )
            latency_ms = adapter_result.latency_ms
        except DecisionAdapterError as exc:
            error_code = exc.error_code
            input_payload = self._fallback_input(signal)
            input_hash = _hash_payload(input_payload)
            output = _safe_reject(signal, error_code)
            latency_ms = None
        elapsed_ms = int((perf_counter() - started) * 1000)
        return await self._repository.record(
            signal=signal,
            adapter=adapter_name,
            model_name=model_name,
            prompt_version=self._settings.openai_decision_prompt_version,
            input_hash=input_hash,
            input_payload=input_payload,
            output=output,
            output_payload=output.model_dump(mode="json"),
            status="FAILED" if error_code else "COMPLETED",
            request_id=request_id,
            latency_ms=latency_ms if latency_ms is not None else elapsed_ms,
            error_code=error_code,
            evaluation_key=None if force else evaluation_key,
        )

    async def recommendations(self, *, limit: int = 100) -> list[dict[str, object]]:
        bounded = max(1, min(limit, 500))
        return [
            item.as_dict()
            for item in await self._repository.list_recommendations(limit=bounded)
        ]

    def _adapter_name(self) -> str:
        adapter = self._settings.openai_decision_adapter.strip().lower()
        if adapter not in {"fake", "openai"}:
            raise DecisionConfigError("Unsupported OpenAI decision adapter.")
        return adapter

    def _model_name(self, adapter: str) -> str:
        if adapter == "fake":
            return self._settings.openai_model or "fake"
        return self._settings.openai_model

    def _build_input(self, signal: DecisionSignal) -> DecisionInput:
        features = signal.features
        indicators = features.get("indicator_values")
        quality = features.get("data_quality")
        future = features.get("future_live_qualification", {})
        if not isinstance(indicators, Mapping) or not isinstance(quality, Mapping):
            raise DecisionAdapterError("signal_features_missing")
        if not isinstance(future, Mapping):
            raise DecisionAdapterError("signal_features_invalid")
        return DecisionInput(
            signal_id=signal.id,
            signal_key=signal.signal_key,
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            strategy_version=signal.strategy_version,
            timestamp_ist=signal.signal_time.astimezone(IST).isoformat(),
            signal_status=signal.signal_status,
            indicator_values={
                key: None if value is None else str(value)
                for key, value in indicators.items()
                if key in ALLOWED_INDICATORS
            },
            data_quality={
                key: bool(value)
                for key, value in quality.items()
                if key in ALLOWED_DATA_QUALITY
            },
            future_live_qualification={
                key: value
                for key, value in future.items()
                if key in ALLOWED_FUTURE_QUALIFICATION
            },
            paper_state=DecisionPaperState(
                enabled=self._settings.paper_enabled,
                mode=self._settings.paper_mode,
                max_trades_per_day=self._settings.paper_max_trades_per_day,
            ),
            limits=DecisionLimits(
                max_trade_notional_inr=self._settings.max_trade_notional_inr,
                max_planned_risk_inr=self._settings.max_planned_risk_per_trade_inr,
                max_daily_loss_inr=self._settings.max_daily_loss_inr,
            ),
        )

    def _fallback_input(self, signal: DecisionSignal) -> dict[str, object]:
        return {
            "signal_id": signal.id,
            "signal_key": signal.signal_key,
            "symbol": signal.symbol,
            "strategy": signal.strategy_name,
            "strategy_version": signal.strategy_version,
            "timestamp_ist": signal.signal_time.astimezone(IST).isoformat(),
            "signal_status": signal.signal_status,
        }

    def _validate_output(
        self,
        raw_output: object,
        *,
        signal: DecisionSignal,
    ) -> tuple[DecisionOutput, str | None]:
        if not isinstance(raw_output, dict):
            return _safe_reject(signal, "malformed_output"), "malformed_output"
        prohibited = _find_prohibited_key(raw_output)
        if prohibited is not None:
            return _safe_reject(signal, "prohibited_output_field"), "prohibited_output_field"
        if EXTERNAL_FACT_PATTERN.search(json.dumps(raw_output, sort_keys=True)):
            return _safe_reject(signal, "external_fact_claim"), "external_fact_claim"
        try:
            output = DecisionOutput.model_validate(raw_output)
        except ValidationError:
            return _safe_reject(signal, "schema_validation_failed"), "schema_validation_failed"
        if output.strategy_template not in P05_STRATEGIES:
            return _safe_reject(signal, "strategy_not_allowlisted"), "strategy_not_allowlisted"
        if output.strategy_template != signal.strategy_name:
            return _safe_reject(signal, "strategy_mismatch"), "strategy_mismatch"
        if output.data_sufficiency == DataSufficiency.INSUFFICIENT:
            return _safe_reject(signal, "data_insufficient"), "data_insufficient"
        if (
            output.verdict == DecisionVerdict.ELIGIBLE
            and output.confidence < self._settings.openai_decision_min_confidence
        ):
            return _safe_reject(signal, "eligible_confidence_below_minimum"), (
                "eligible_confidence_below_minimum"
            )
        return output, None


def _find_prohibited_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in PROHIBITED_KEY_FRAGMENTS):
                return normalized
            found = _find_prohibited_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_prohibited_key(item)
            if found is not None:
                return found
    return None


def _safe_reject(signal: DecisionSignal, reason: str) -> DecisionOutput:
    return DecisionOutput(
        verdict=DecisionVerdict.REJECT,
        strategy_template=signal.strategy_name,
        confidence=0,
        reasons=[reason],
        warnings=[],
        recommended_stop_method=None,
        recommended_target_r_multiple=None,
        data_sufficiency=DataSufficiency.INSUFFICIENT,
    )


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_key(
    *,
    signal: DecisionSignal,
    adapter: str,
    model_name: str,
    prompt_version: str,
) -> str:
    raw = f"{signal.id}:{signal.signal_key}:{adapter}:{model_name}:{prompt_version}"
    return hashlib.sha256(raw.encode()).hexdigest()
