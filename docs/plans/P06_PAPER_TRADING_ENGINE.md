# P06 — Paper Trading Engine and Journal


## Objective

Exercise the trade lifecycle using live or replayed signals while keeping broker writes impossible.

## Deliverables

- Trading-mode service implementing `OFF`, `SHADOW`, `PAPER`, `LIVE` enum, with LIVE still disabled/not implemented.
- Paper broker simulator:
  - accepts approved simulated instruction structures;
  - defines reproducible limit-fill assumptions;
  - models entry, protective stop, target and time/force-flat exit;
  - stores paper orders, events and fills in the same durable shapes intended for live use.
- Trade journal:
  - signal context;
  - planned entry/stop/target/risk;
  - paper fills;
  - exit reason;
  - gross P&L;
  - configurable estimated-cost field.
- End-of-session paper report endpoint/CLI.
- SHADOW mode: log candidates but never simulate orders.
- PAPER mode: simulate only after non-AI deterministic placeholder acceptance for testing; actual AI is added in P07.

## Safety requirements

- No real order client may be imported/called by paper engine.
- LIVE must raise an explicit “not implemented/disabled” error.
- All paper records must be marked clearly as simulated.

## Tests

- Simulated limit fill and no-fill paths.
- Stop hit, target hit, time exit and force-flat.
- Duplicate candidate cannot open duplicate paper trade.
- Journal P&L reconciliation.
- OFF/SHADOW can never generate paper fills.

## Acceptance criteria

- Historical replay and live stream can produce paper journal outcomes.
- User can inspect why every paper trade opened/closed.
- Real execution remains impossible.

## Codex prompt

```text
Implement only P06_PAPER_TRADING_ENGINE.

Build SHADOW/PAPER handling, a deterministic paper broker simulator and durable journal/reporting.
LIVE execution must remain disabled and tested as disabled.
Use no real broker-order calls.
Run replay-based and lifecycle tests.
```
