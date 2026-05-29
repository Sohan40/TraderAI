# P08 — Deterministic Automatic Approval and Position Sizing


## Objective

Implement the true automatic approval system. It evaluates a schema-valid eligible decision and either creates a bounded approved instruction or rejects it. It remains usable in PAPER only until execution is added.

## Deliverables

- Risk configuration stored/versioned and loaded safely.
- `RiskEngine.evaluate(...)` consuming:
  - immutable candidate snapshot;
  - validated AI decision;
  - session/mode state;
  - available cash/margins snapshot;
  - open/pending trade state;
  - data-health status.
- Decimal price/tick rounding.
- Quantity calculation and stop/target instruction.
- Immutable `risk_checks` record with pass/reject reasons.
- Approved instruction expiration and idempotency key.
- Daily loss/trade/open-position caps.
- Time-window and force-flat checks.
- PAPER pipeline now executes only passed risk instructions.

## Initial live configuration encoded as defaults

- ₹500 maximum trade notional.
- ₹10 maximum planned risk/trade.
- ₹20 daily loss.
- One open position.
- One entry/day.
- ₹1,000 reserve.
- Long only, allowlisted cash instruments.
- Limit entries only.
- No new entries after 14:30 IST; force-flat rule by 15:10 IST.

## Safety requirements

- Risk check is deterministic and unit-tested.
- AI cannot supply quantity.
- A failed/expired instruction never executes even in PAPER.
- Any missing required state means reject.

## Tests

- Quantity by risk/notional/cash minimum.
- Tick-size rounding.
- All each veto rule independently.
- Daily cap and concurrent-position rejection.
- Stale data/instruction rejection.
- Repeat input cannot create duplicate instruction.

## Acceptance criteria

- All paper orders originate from passed risk checks.
- Rejected candidates have explicit persisted reasons.
- Safety invariants have high test coverage.

## Codex prompt

```text
Implement only P08_RISK_ENGINE.

Add deterministic automatic approval, sizing, risk-check persistence and paper integration.
Use Decimal arithmetic and explicit tick-size rounding.
Encode the initial low INR caps from docs/RISK_RULES.md.
Do not add live broker order placement.
Thoroughly test every veto and idempotency path.
```
