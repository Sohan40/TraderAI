# P11 — Observability, Alerts and End-of-Day Analytics


## Objective

Make autonomous behaviour debuggable before any micro-live activation.

## Deliverables

- Structured log context fields:
  - correlation/session IDs;
  - candidate ID;
  - risk-check ID;
  - instruction ID;
  - internal/broker order identifiers where safe;
  - symbol;
  - state transition;
  - mode.
- Metrics/status for:
  - WebSocket heartbeat age;
  - reconnect count;
  - scanner candidates and vetoes;
  - model latency/errors/verdicts;
  - risk pass/rejection reasons;
  - broker order states/rejections;
  - protective-exit confirmation time;
  - open exposure;
  - daily P&L;
  - kill-switch state.
- Alert mechanism chosen for personal operation, such as email/Telegram/Cloud Monitoring, for:
  - active live order;
  - protective-order failure;
  - kill switch activation;
  - stale stream/session failure;
  - force-flat event.
- End-of-day report:
  - candidates;
  - decisions;
  - risk passes/rejections;
  - paper/live trades;
  - gross and estimated/net P&L;
  - execution issues;
  - model/API usage.
- Incident workflow linked to template.

## Safety requirements

- Redact tokens/secrets and unnecessary personal data.
- Observability outage in LIVE with an open position triggers risk-defined behaviour.
- Reports distinguish PAPER from LIVE prominently.

## Tests

- Redaction tests.
- Alert on protection failure and kill switch.
- EOD reconciliation from fixture order events/trades.
- Live versus paper labels cannot be confused.

## Acceptance criteria

- A full PAPER day can be audited without looking at raw database rows.
- Critical unsafe failures create immediate alerts.
- Monitoring evidence is available for rollout gate review.

## Codex prompt

```text
Implement only P11_OBSERVABILITY_AND_EOD_ANALYTICS.

Add structured audit logs, health/metric reporting, critical alerts and end-of-day analytics/reconciliation.
Never log secrets or raw tokens. Ensure PAPER versus LIVE is unmistakable.
Add tests for redaction, protection-failure alerts, kill-switch alerts and report reconciliation.
```
