# P12 — Micro-Live Autonomous Rollout


## Objective

Move from tested simulation to tightly bounded autonomous real execution only after objective gates pass. This phase is primarily a controlled runbook and configuration activation, not new strategy development.

## Pre-live gate checklist

All must be documented as passed:

- [ ] Unit, integration and safety tests green.
- [ ] GCP VM stable; reserved static IP verified and configured for broker order rules.
- [ ] Secret Manager and logging redaction reviewed.
- [ ] Daily Kite authentication/session flow works.
- [ ] Market data has run in SHADOW for at least five sessions with acceptable heartbeat/reconnect behaviour.
- [ ] PAPER pipeline has completed at least twenty simulated closed trades.
- [ ] Protective exit, force-flat and kill-switch paths tested in PAPER.
- [ ] Controlled broker connectivity/order lifecycle testing is manually reviewed and executed with extreme care because no sandbox is assumed.
- [ ] Dashboard arm/disarm/kill controls tested.
- [ ] Live configuration diff reviewed against `docs/RISK_RULES.md`.
- [ ] Owner accepts possible loss of allocated money and confirms no strategy-return expectation.

## First live configuration

| Setting | Required value |
|---|---:|
| Max trade notional | ₹500 |
| Max planned risk/trade | ₹10 |
| Max trades/day | 1 |
| Max concurrent positions | 1 |
| Max daily loss | ₹20 |
| Direction | Long only |
| Symbol universe | Small manually allowlisted liquid cash instruments only |
| Strategy | One strategy only |
| Entry order | Limit only |
| Entry cutoff | 14:30 IST or earlier |
| Force-flat | 15:10 IST or earlier if operationally required |

## Daily live runbook

### Before market activity

1. Confirm deployment version and no open incidents.
2. Log in to Kite through the backend dashboard.
3. Verify broker session validity and read-only margins.
4. Confirm WebSocket stream and completed-bar health.
5. Confirm no open or pending position/orders requiring reconciliation.
6. Confirm risk configuration and allowed strategy/symbols.
7. Set mode LIVE and deliberately arm only until the stated session cutoff.

### During armed session

- The system may automatically enter one passed, risk-approved trade.
- Watch visible order, fill and protection states.
- A protective-exit failure or health failure activates kill switch.
- Do not manually interfere without recording an incident unless needed to limit loss.

### At or before force-flat time

- Confirm no intraday position remains open.
- Disarm and set mode OFF.
- Run EOD report and compare journal against broker state.

## Stop and review rules

Set mode OFF and do not re-arm until reviewed when any occurs:

- Unprotected live position at any point.
- Incorrect quantity, symbol, side, price or product.
- Unexpected charge/slippage behaviour.
- Loss limit breached unexpectedly.
- Token, IP, WebSocket, database or worker failure affecting control.
- Journal and broker state disagree.
- Model output violates allowed-data contract.

## Progression after initial live tests

After ten correctly controlled micro-live closed trades with no operational safety failure, produce a written review containing:

- execution reliability;
- protective-exit performance;
- kill-switch incidents;
- net costs and P&L;
- whether AI decision layer helped or merely added noise;
- recommendation to stop, continue unchanged or propose a documented cap increase.

Do not increase capital merely because the first few trades win.

## Codex prompt

```text
Read AGENTS.md, docs/RISK_RULES.md and docs/plans/P12_MICRO_LIVE_ROLLOUT.md.

Implement only missing rollout-gate status surfaces, configuration validation, runbook automation that
does not place orders itself, and tests for the stated caps/gates. Do not loosen risk caps or auto-arm.
Provide a deployment checklist and a human-reviewed configuration diff required before LIVE use.
```
