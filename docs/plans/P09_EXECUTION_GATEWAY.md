# P09 — Locked-Down Kite Execution Gateway


## Objective

Implement the broker-order capability behind strict gates, disabled by default. This is the first phase containing live-order code; tests remain fully mocked.

## Deliverables

- Order-writing broker interface and Kite adapter for required operations only:
  - place limit entry;
  - cancel pending entry;
  - place/monitor protective exit using supported broker order type selected during implementation;
  - fetch/reconcile orders and positions.
- Execution Gateway checks before any broker write:
  - LIVE mode;
  - owner-armed, unexpired live session;
  - valid Kite session;
  - static-IP deployment readiness configured;
  - no active kill switch;
  - fresh passed risk instruction;
  - exact quantity/price/stop from instruction;
  - idempotency lock.
- Broker order tagging scheme linking to internal instruction ID.
- Order-event reconciliation from broker updates and fallback fetch.
- Immediate protective-exit workflow after fill.
- Emergency workflow when protection fails.
- Global `ALLOW_LIVE_BROKER_WRITES=false` additional deployment lock by default.

## Safety requirements

- No route to submit arbitrary user/model order JSON.
- All test broker adapters are fakes; tests assert no network call.
- The live adapter requires multiple explicit environment/config gates.
- Real connectivity testing is not performed automatically by Codex or CI.
- Any protective-exit failure activates kill switch.

## Tests

- Live disabled by each missing gate.
- Idempotent duplicate request.
- Entry acknowledged but not filled.
- Partial/full fill handling as designed.
- Protective exit confirmed/fails.
- Broker rejection and session invalidation.
- Restart/reconciliation with open position.

## Acceptance criteria

- Code supports an intentionally reviewed live test, but production/default remains off.
- No live request can bypass risk record, mode, arming or kill switch.
- Every order lifecycle state is durable.

## Codex prompt

```text
Implement only P09_EXECUTION_GATEWAY.

Add a gated Kite order adapter and execution gateway behind ALLOW_LIVE_BROKER_WRITES=false,
TRADING_MODE=OFF and LIVE_ARMED=false defaults.
All tests must mock the broker. Do not place any real test order.
Protective exit and kill-switch-on-failure are mandatory.
Report the manual controlled-connectivity test procedure but do not run it.
```
