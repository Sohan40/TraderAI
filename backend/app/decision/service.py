"""Operator-triggered P07 structured decision orchestration."""

from __future__ import annotations

import asyncio
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
    EvaluationMode,
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
        self._evaluation_lock = asyncio.Lock()

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
            "evaluation_mode": self._evaluation_mode().value,
            "automatic_evaluation_enabled": (
                self._settings.market_ops_decision_auto_evaluate_enabled
            ),
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
            evaluation_mode=self._evaluation_mode().value,
        )
        async with self._evaluation_lock:
            return await self._evaluate_locked(
                signal=signal,
                adapter_name=adapter_name,
                model_name=model_name,
                evaluation_key=evaluation_key,
                force=force,
            )

    async def _evaluate_locked(
        self,
        *,
        signal: DecisionSignal,
        adapter_name: str,
        model_name: str,
        evaluation_key: str,
        force: bool,
    ) -> PersistedDecision:
        if not force:
            existing = await self._repository.find_by_evaluation_key(
                evaluation_key=evaluation_key
            )
            if existing is not None:
                return existing

        started = perf_counter()
        error_code: str | None = None
        request_id: str | None = None
        raw_output_payload: dict[str, object] = {}
        try:
            decision_input = self._build_input(signal)
            input_payload = decision_input.model_dump(mode="json")
            input_hash = _hash_payload(input_payload)
            adapter_result = await self._adapter.evaluate(decision_input)
            request_id = adapter_result.request_id
            secrets = _configured_secrets(self._settings)
            raw_output_payload = _sanitize_raw_output(
                adapter_result.output,
                secrets=secrets,
            )
            output, error_code = self._validate_output(
                adapter_result.output,
                signal=signal,
                decision_input=decision_input,
                secrets=secrets,
            )
            latency_ms = adapter_result.latency_ms
        except DecisionAdapterError as exc:
            error_code = exc.error_code
            input_payload = self._fallback_input(signal)
            input_hash = _hash_payload(input_payload)
            output = _safe_reject(signal, error_code)
            raw_output_payload = {"error_code": error_code}
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
            output_payload=raw_output_payload,
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

    def evaluation_identity(self) -> dict[str, str]:
        adapter = self._adapter_name()
        return {
            "adapter": adapter,
            "model_name": self._model_name(adapter),
            "prompt_version": self._settings.openai_decision_prompt_version,
            "evaluation_mode": self._evaluation_mode().value,
        }

    def _evaluation_mode(self) -> EvaluationMode:
        try:
            return EvaluationMode(self._settings.openai_decision_evaluation_mode.strip().upper())
        except ValueError as exc:
            raise DecisionConfigError("Unsupported OpenAI decision evaluation mode.") from exc

    def _build_input(self, signal: DecisionSignal) -> DecisionInput:
        features = signal.features
        indicators = features.get("indicator_values")
        quality = features.get("data_quality")
        future = features.get("future_live_qualification", {})
        if not isinstance(indicators, Mapping) or not isinstance(quality, Mapping):
            raise DecisionAdapterError("signal_features_missing")
        if not isinstance(future, Mapping):
            raise DecisionAdapterError("signal_features_invalid")
        evaluation_mode = self._evaluation_mode()
        evaluation_warnings = _evaluation_context_warnings(
            quality=quality,
            future=future,
        )
        return DecisionInput(
            signal_id=signal.id,
            signal_key=signal.signal_key,
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            strategy_version=signal.strategy_version,
            timestamp_ist=signal.signal_time.astimezone(IST).isoformat(),
            signal_status=signal.signal_status,
            evaluation_mode=evaluation_mode,
            evaluation_warnings=evaluation_warnings,
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
            "evaluation_mode": self._evaluation_mode().value,
        }

    def _validate_output(
        self,
        raw_output: object,
        *,
        signal: DecisionSignal,
        decision_input: DecisionInput,
        secrets: tuple[str, ...],
    ) -> tuple[DecisionOutput, str | None]:
        if not isinstance(raw_output, dict):
            return _safe_reject(signal, "malformed_output"), "malformed_output"
        prohibited = _find_prohibited_key(raw_output)
        if prohibited is not None:
            return _safe_reject(signal, "prohibited_output_field"), "prohibited_output_field"
        if _contains_secret_value(raw_output, secrets=secrets):
            return _safe_reject(signal, "prohibited_output_value"), "prohibited_output_value"
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
        if output.verdict == DecisionVerdict.ELIGIBLE:
            context_warnings = _eligibility_context_warnings(decision_input)
            if (
                decision_input.evaluation_mode == EvaluationMode.LIVE_SHADOW
                and context_warnings
            ):
                return _shadow_watch(output, context_warnings), None
            if (
                decision_input.evaluation_mode == EvaluationMode.FUTURE_LIVE_ELIGIBILITY
                and context_warnings
            ):
                return _safe_reject(signal, "future_live_context_incomplete"), (
                    "future_live_context_incomplete"
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


def _shadow_watch(output: DecisionOutput, warnings: list[str]) -> DecisionOutput:
    return DecisionOutput(
        verdict=DecisionVerdict.WATCH,
        strategy_template=output.strategy_template,
        confidence=output.confidence,
        reasons=list(output.reasons),
        warnings=list(dict.fromkeys([*output.warnings, *warnings])),
        recommended_stop_method=None,
        recommended_target_r_multiple=None,
        data_sufficiency=output.data_sufficiency,
    )


def _evaluation_context_warnings(
    *,
    quality: Mapping[object, object],
    future: Mapping[object, object],
) -> list[str]:
    warnings: list[str] = []
    if not bool(quality.get("quote_fresh")):
        warnings.append("quote_fresh_missing")
    if not bool(quality.get("spread_available")):
        warnings.append("spread_data_missing")
    if bool(future.get("spread_required")) and not bool(future.get("spread_validated")):
        warnings.append("spread_validation_missing")
    return list(dict.fromkeys(warnings))


def _eligibility_context_warnings(decision_input: DecisionInput) -> list[str]:
    warnings: list[str] = []
    if not decision_input.data_quality.get("quote_fresh", False):
        warnings.append("quote_fresh_missing")
    if bool(decision_input.future_live_qualification.get("spread_required")) and not bool(
        decision_input.future_live_qualification.get("spread_validated")
    ):
        warnings.append("spread_validation_missing")
    return warnings


def _sanitize_raw_output(
    value: object,
    *,
    secrets: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"diagnostic": "non_object_output"}
    sanitized = _sanitize_mapping(value, secrets=secrets)
    return sanitized if isinstance(sanitized, dict) else {"diagnostic": "sanitized_output"}


def _sanitize_mapping(value: object, *, secrets: tuple[str, ...]) -> object:
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in PROHIBITED_KEY_FRAGMENTS):
                continue
            output[str(key)] = _sanitize_mapping(nested, secrets=secrets)
        return output
    if isinstance(value, list):
        return [_sanitize_mapping(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        safe = value
        for secret in secrets:
            safe = safe.replace(secret, "[redacted]")
        return safe
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _contains_secret_value(value: object, *, secrets: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(_contains_secret_value(item, secrets=secrets) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_value(item, secrets=secrets) for item in value)
    return isinstance(value, str) and any(secret in value for secret in secrets)


def _configured_secrets(settings: Settings) -> tuple[str, ...]:
    values = (
        settings.openai_api_key,
        settings.operator_auth_token,
        settings.kite_api_key,
        settings.kite_api_secret,
        settings.kite_session_encryption_key,
        settings.market_ops_telegram_bot_token,
        settings.market_ops_telegram_chat_id,
        settings.database_url,
        settings.redis_url,
    )
    return tuple(value for value in values if value)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_key(
    *,
    signal: DecisionSignal,
    adapter: str,
    model_name: str,
    prompt_version: str,
    evaluation_mode: str,
) -> str:
    raw = (
        f"{signal.id}:{signal.signal_key}:{adapter}:{model_name}:"
        f"{prompt_version}:{evaluation_mode}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()
