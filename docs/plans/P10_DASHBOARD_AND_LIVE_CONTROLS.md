# P10 — Dashboard, Daily Arming and Kill Switch


## Objective

Create the operator interface required to observe and deliberately arm autonomous execution for a limited daily session.

## Deliverables

- Next.js frontend or minimal selected frontend framework documented.
- Authentication/access protection appropriate for a personal control panel.
- Screens:
  - system status: mode, deployment version, Kite session, WebSocket heartbeat, worker health;
  - daily Zerodha connect/session flow;
  - allowlisted watchlist and strategy enablement;
  - candidates and AI verdicts;
  - risk approvals/rejections;
  - orders/fills/open position/protective status;
  - journal and daily P&L.
- Live controls:
  - change mode OFF/SHADOW/PAPER;
  - LIVE arming confirmation requiring visible review of active caps and current session;
  - armed expiration no later than the configured intraday cutoff;
  - DISARM action;
  - KILL SWITCH action;
  - force-flat action with explicit confirmation and audit record.
- Backend authorization/audit for every control action.

## Safety requirements

- The frontend never constructs broker payloads or holds API secrets.
- LIVE arming cannot proceed without healthy session/data/storage/worker and visible active risk policy.
- Reload/redeploy/restart never silently restores an armed state.
- Kill switch is highly visible and reachable.

## Tests

- Control authorization.
- Arm rejection under unhealthy prerequisites.
- Arm expiry/disarm.
- Kill switch freezes new entry path.
- Audit event for every control action.
- Frontend displays dangerous/live state unmistakably.

## Acceptance criteria

- Owner can see what the system is doing and stop it rapidly.
- Live session arming is deliberate, time-limited and recorded.
- No per-trade approval is necessary once armed, while deterministic gates remain active.

## Codex prompt

```text
Implement only P10_DASHBOARD_AND_LIVE_CONTROLS.

Add the personal dashboard and backend control endpoints for status, session, PAPER/SHADOW control,
time-limited LIVE arming, disarm, kill switch and audited force-flat confirmation.

The UI must never possess broker credentials or submit arbitrary orders.
Add tests proving unhealthy systems cannot be armed and kill switch blocks entries.
```
