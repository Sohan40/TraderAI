# Testing and Rollout Gates

## Test layers

| Layer | Required tests |
|---|---|
| Unit | indicators, scanner boundaries, sizing, tick rounding, loss limits, state transitions |
| Contract | Kite/OpenAI fake adapter payload parsing and errors |
| Integration | PostgreSQL/Redis, API/worker coordination, event persistence |
| Replay | historical completed-candle sequence through scanner/risk pipeline |
| Shadow live | WebSocket ingestion and candidates with zero broker order path |
| Paper live | simulated fill/stop/exit through full pipeline |
| Controlled connectivity | deliberately reviewed order path tests with live risk explicitly bounded |
| Micro live | armed autonomous session with tiny cap and full monitoring |

## Mandatory scenario tests

- AI says `ELIGIBLE`, risk rejects due to daily loss cap.
- AI says `ELIGIBLE`, risk rejects due to quantity zero.
- AI response malformed; no order created.
- Data becomes stale after signal; order instruction expires.
- Pending entry exists; new candidate rejected.
- Entry fill occurs; protective exit placement succeeds and is recorded.
- Entry fill occurs; protective exit placement fails; kill switch activates.
- WebSocket heartbeat goes stale during live armed state; new entries freeze.
- Restart occurs with an open broker position; system reconciles before allowing entry.
- Force-flat time is reached with open position; configured exit escalation occurs.
- Duplicate event or retry cannot create a duplicate live order.

## Rollout ladder

| Gate | Minimum pass condition | Next mode |
|---|---|---|
| Build/test | All unit/integration checks pass | SHADOW |
| SHADOW | Five market sessions; stable ingestion; no phantom/live order path | PAPER |
| PAPER | Twenty closed simulated trades; journal reconciles; exit/kill paths tested | Connectivity testing |
| Connectivity testing | Explicitly reviewed real broker path and protective-order handling | Micro LIVE |
| Micro LIVE initial | One entry/day, ₹500 notional cap, ₹10 planned risk, ₹20 daily loss cap | Continue or stop |
| Limit reconsideration | Ten micro-live closed trades without operational safety failures | Documented review only |

## Operational review after every live day

- Did any order or exit differ from the approved instruction?
- Was protective exit confirmed promptly?
- Were P&L and charges captured/reconciled?
- Did any data, token or broker health issue occur?
- Did the agent explanation stay within supplied data?
- Did the risk engine reject candidates it should have rejected?
- Keep live mode OFF until any incident is understood.
