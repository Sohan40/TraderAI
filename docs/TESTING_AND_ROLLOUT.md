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

## P05 Scanner Validation

P05 scanners run only on completed stored candles or explicit replay fixtures. They emit immutable observations and do not create orders, paper fills, OpenAI requests, Kronos calls or MCP calls. Replay is invoked with:

```text
python -m app.scanners.replay --symbol NSE:SBIN --timeframe 1minute --fixture path/to/bars.json
```

The fixture must contain completed OHLCV rows. Identical fixture/configuration input should produce identical candidate/rejection counts and signal keys.

## P05.5-P05.7 Operations Validation

Validate the configured watchlist and local stream gates before stream start:

```text
GET /api/v1/market-data/watchlist/validate
GET /api/v1/market-data/stream/readiness
GET /api/v1/ops/morning-readiness
```

Scanner batch and auto-loop validation must prove per-symbol failure isolation,
no overlapping scheduled runs, completed-candle-only reads, candidate
persistence, disabled rejection persistence by default, and disabled auto-loop
defaults. The detailed operator sequence is in
`docs/WATCHLIST_AND_SCANNER_OPERATIONS.md`.

## P05.8 Universe Validation

Universe tests must prove deterministic ranking, explicit exclusions for
missing or inadequate data, dry-run persistence behavior, compact run retrieval,
and disabled-by-default scanner integration. A configured pool is not considered
rankable until completed local candles exist.

## P06 Paper Validation

P06 paper replay is disabled by default with `PAPER_ENABLED=false` and `PAPER_MODE=OFF`. In `PAPER` mode it consumes only persisted P05 `CANDIDATE` signals and completed `1minute` candles. Entry is a simulated long-only limit buy; stop and target are checked on later candles, with stop winning if both stop and target touch in the same candle. If the replay reaches the configured force-flat time, default `15:10` IST, the trade exits at that candle close. If data ends earlier, the trade exits at the last later candle close with `TIME_EXIT`, or records `DATA_ENDED` if no later candle exists.

Replay is invoked with:

```text
python -m app.paper.replay --symbol NSE:SBIN --from 2026-06-03T03:45:00Z --to 2026-06-03T09:45:00Z --enable-paper
```

P06 never calls Kite, OpenAI, Kronos or MCP, and `LIVE` remains disabled/not implemented.

## Operational review after every live day

- Did any order or exit differ from the approved instruction?
- Was protective exit confirmed promptly?
- Were P&L and charges captured/reconciled?
- Did any data, token or broker health issue occur?
- Did the agent explanation stay within supplied data?
- Did the risk engine reject candidates it should have rejected?
- Keep live mode OFF until any incident is understood.
