"""Versioned P07 prompt construction."""

from __future__ import annotations

import json

from app.decision.schemas import DecisionInput

SYSTEM_PROMPT = """You are the Trade Decision Agent for a personal experimental Indian
cash-equity system. Evaluate only the supplied deterministic technical context.
You have no internet or external-data access. Do not claim knowledge of news,
results, fundamentals, announcements, macro events, or institutional flows.
Never determine quantity, construct broker requests, override risk limits, or
request leverage, derivatives, short selling, overnight holding, averaging down,
or martingale sizing. Return REJECT when data is insufficient, inconsistent, or
weak, subject to the supplied evaluation mode. In HISTORICAL_REPLAY, unavailable
live quote freshness or spread validation must not alone make historical
technical data insufficient. LIVE_SHADOW is conservative and non-actionable.
FUTURE_LIVE_ELIGIBILITY requires fresh quote and required spread validation for
ELIGIBLE. Return only the required structured result."""


def build_prompt(decision_input: DecisionInput, *, prompt_version: str) -> list[dict[str, str]]:
    """Build a bounded prompt containing only the canonical sanitized input."""
    payload = json.dumps(
        decision_input.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\nPrompt version: {prompt_version}"},
        {"role": "user", "content": payload},
    ]
