"""Decision adapter protocol."""

from __future__ import annotations

from typing import Protocol

from app.decision.schemas import AdapterResult, DecisionInput


class DecisionAdapter(Protocol):
    async def evaluate(self, decision_input: DecisionInput) -> AdapterResult: ...
