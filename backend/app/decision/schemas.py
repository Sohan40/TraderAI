"""Strict P07 decision value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DecisionVerdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    WATCH = "WATCH"
    REJECT = "REJECT"


class DataSufficiency(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


StopMethod = Literal["breakout_failure_or_atr", "vwap_failure_or_atr"]


class DecisionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_trade_notional_inr: float = Field(ge=0)
    max_planned_risk_inr: float = Field(ge=0)
    max_daily_loss_inr: float = Field(ge=0)


class DecisionPaperState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    mode: str
    max_trades_per_day: int = Field(ge=0)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: int = Field(gt=0)
    signal_key: str
    symbol: str
    strategy: str
    strategy_version: str
    timestamp_ist: str
    signal_status: str
    indicator_values: dict[str, str | None]
    data_quality: dict[str, bool]
    future_live_qualification: dict[str, object]
    paper_state: DecisionPaperState
    limits: DecisionLimits


class DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: DecisionVerdict
    strategy_template: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    recommended_stop_method: StopMethod | None
    recommended_target_r_multiple: float | None = Field(default=None, ge=0.5, le=5.0)
    data_sufficiency: DataSufficiency


@dataclass(frozen=True)
class DecisionSignal:
    id: int
    signal_key: str
    symbol: str
    strategy_name: str
    strategy_version: str
    signal_status: str
    signal_time: datetime
    features: dict[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    output: object
    request_id: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class PersistedDecision:
    recommendation_id: int
    model_run_id: int
    signal_id: int
    signal_key: str
    symbol: str
    strategy: str
    verdict: str
    confidence: float
    reasons: list[str]
    warnings: list[str]
    data_sufficiency: str
    adapter: str
    model_name: str
    prompt_version: str
    status: str
    error_code: str | None
    created_at: datetime
    existing: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "model_run_id": self.model_run_id,
            "signal_id": self.signal_id,
            "signal_key": self.signal_key,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "data_sufficiency": self.data_sufficiency,
            "adapter": self.adapter,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "error_code": self.error_code,
            "created_at": self.created_at.isoformat(),
            "existing": self.existing,
        }
