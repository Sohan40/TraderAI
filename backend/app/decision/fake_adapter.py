"""Deterministic fake decision adapter."""

from __future__ import annotations

from app.decision.schemas import AdapterResult, DecisionInput


class FakeDecisionAdapter:
    """Return a conservative deterministic result without network access."""

    def __init__(self, output: object | None = None) -> None:
        self._output = output
        self.calls: list[DecisionInput] = []

    async def evaluate(self, decision_input: DecisionInput) -> AdapterResult:
        self.calls.append(decision_input)
        output = self._output or {
            "verdict": "WATCH",
            "strategy_template": decision_input.strategy,
            "confidence": 0.5,
            "reasons": ["fake_adapter_manual_review"],
            "warnings": ["fake_adapter"],
            "recommended_stop_method": None,
            "recommended_target_r_multiple": None,
            "data_sufficiency": "SUFFICIENT",
        }
        return AdapterResult(output=output, request_id="fake", latency_ms=0)
