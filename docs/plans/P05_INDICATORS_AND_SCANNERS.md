# P05 — Indicators and Candidate Scanners


## Objective

Generate deterministic trade candidates from completed bars. Candidates are observations only and cannot become orders.

## Deliverables

- Indicator functions with explicit minimum-history handling:
  - EMA 9/20/50;
  - RSI 14;
  - ATR 14;
  - VWAP;
  - opening-range high/low;
  - previous-day high/low where data is available;
  - volume ratio;
  - relative index movement;
  - spread percentage when depth snapshot available.
- Scanner framework with immutable feature snapshot persisted in `signals`.
- Implement two candidate strategies:
  1. `opening_range_breakout_long`;
  2. `vwap_pullback_continuation_long`.
- Configuration enables one strategy for future live eligibility; both may run in shadow/paper.
- Hard preliminary vetoes:
  - unsupported symbol;
  - missing history;
  - stale quote;
  - spread too wide;
  - outside configured time window;
  - data-quality failure.
- Replay CLI that runs completed historical bars through scanner logic.

## Safety requirements

- A scanner emits `CANDIDATE` or `REJECTED_SIGNAL`, never a broker instruction.
- No OpenAI, no order gateway.
- Feature snapshot cannot be changed after emission.

## Tests

- Indicator known-value/unit tests.
- Scanner boundary tests around entry time, spread and volume thresholds.
- Replay determinism: same bars give same signal output.
- Stale/missing data always vetoes.

## Acceptance criteria

- Candidate signals can be replayed and examined in a table/API.
- Preliminary veto reason is saved.
- No candidate can trigger a real action.

## Codex prompt

```text
Implement only P05_INDICATORS_AND_SCANNERS.

Add deterministic indicator library, scanner framework, the two specified strategies, preliminary
vetoes, historical replay CLI and thorough unit tests.

No AI module and no broker order code. Candidates must be immutable data records only.
```
