"""Paper journal report helpers."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from app.paper.schemas import PAPER_ENTRY_FILLED, PAPER_ENTRY_NO_FILL, PaperMode


def build_paper_report(
    *,
    paper_enabled: bool,
    paper_mode: PaperMode,
    outcomes: list[dict[str, object]],
) -> dict[str, object]:
    """Aggregate bounded paper journal payloads into a non-sensitive report."""
    exit_counts: Counter[str] = Counter()
    gross = Decimal("0")
    costs = Decimal("0")
    net = Decimal("0")
    simulated = 0
    entry_attempts = 0
    no_fills = 0
    filled_trades = 0
    rejections = 0
    for outcome in outcomes:
        if outcome.get("simulated") is True:
            simulated += 1
        reason = str(outcome.get("exit_reason") or "UNKNOWN")
        exit_counts[reason] += 1
        gross += _decimal(outcome.get("gross_pnl"))
        costs += _decimal(outcome.get("estimated_costs"))
        net += _decimal(outcome.get("net_estimated_pnl"))
        entry_status = outcome.get("entry_order_status")
        if entry_status in {PAPER_ENTRY_FILLED, PAPER_ENTRY_NO_FILL}:
            entry_attempts += 1
        if entry_status == PAPER_ENTRY_NO_FILL:
            no_fills += 1
        if entry_status == PAPER_ENTRY_FILLED:
            filled_trades += 1
        if outcome.get("rejection_reason"):
            rejections += 1
    return {
        "paper_enabled": paper_enabled,
        "paper_mode": paper_mode.value,
        "simulated_only": True,
        "journal_outcomes": len(outcomes),
        "candidate_signal_outcomes": len(outcomes),
        "simulated_outcomes": simulated,
        "entry_attempt_outcomes": entry_attempts,
        "no_fill_outcomes": no_fills,
        "filled_paper_trade_outcomes": filled_trades,
        "paper_trade_outcomes": filled_trades,
        "rejections": rejections,
        "gross_pnl": _money(gross),
        "estimated_costs": _money(costs),
        "net_estimated_pnl": _money(net),
        "exit_reason_counts": dict(sorted(exit_counts.items())),
    }


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))
