# Architecture

## Goal

Build a narrow autonomous trading experiment that executes only rule-bounded, low-notional trades for the owner's Zerodha account. The system is designed to observe, reject and stop safely rather than to maximize trade count.

## Core separation of responsibilities

| Component | Owns | Must never own |
|---|---|---|
| Market Data Service | Kite WebSocket ingestion, instrument sync, candle aggregation, data-health heartbeat | Trading decisions |
| Indicator Engine | EMA/RSI/ATR/VWAP/spread and context features | Broker calls |
| Scanner | Deterministic candidate generation | Position sizing or live execution |
| OpenAI Decision Agent | Veto/approve a scanner candidate using supplied JSON only | Web research, quantities, broker payloads, risk overrides |
| Risk Engine | Final automatic approval, sizing, stop/target validation, daily caps | Narrative market claims |
| Execution Gateway | Exact broker call, idempotency, order-state reconciliation, protective exit placement | AI interpretation |
| Journal/Analytics | Durable history, net P&L, failures and metrics | Trading authority |
| Dashboard | Login, arm/disarm, kill switch, visibility | Direct unaudited broker order path |

## Component topology

```text
Browser dashboard
    |
    v
FastAPI API  <----> PostgreSQL
    |                  ^
    |                  |
    v                  |
Redis state/event bus  |
    ^                  |
    |                  |
Worker process --------+
    |
    +--> Kite REST: auth, margins, instruments, orders, positions
    +--> Kite WebSocket: quotes, heartbeat, order updates
    +--> OpenAI Responses API: candidate evaluation only
```

## Runtime modes

| Mode | Data stream | Scanner | AI evaluation | Orders |
|---|---|---|---|---|
| `OFF` | Optional health only | No | No | Never |
| `SHADOW` | Live | Yes | Optional | Never; logs candidate only |
| `PAPER` | Live | Yes | Yes | Simulated fills/exits |
| `LIVE` | Live | Yes | Yes | Real orders only when session armed and all gates pass |

The same candidate/risk pipeline should run in PAPER and LIVE so testing meaningfully exercises live logic.

## Data flow for an entry

1. Kite WebSocket receives tick data.
2. Market Data Service updates heartbeat and aggregates completed one/five-minute bars.
3. Indicator Engine computes deterministic features on a completed bar.
4. Scanner emits a candidate with immutable feature snapshot.
5. Decision Agent receives that snapshot and returns strict JSON: `ELIGIBLE`, `WATCH`, or `REJECT`.
6. Risk Engine consumes the candidate, AI verdict, margin/cash state, daily state and live-data health.
7. If passed, Risk Engine creates an immutable approved order instruction with quantity/stop/target and expiry.
8. Execution Gateway revalidates mode, arming, kill switch, idempotency and instruction freshness.
9. Broker adapter submits a limit entry order.
10. Order updates/fills are persisted.
11. Once entry is filled, a broker-side protective exit must be submitted and confirmed immediately; if that fails, freeze entries and invoke emergency exit rules.
12. Every outcome is journalled.

## Data model

Minimum durable entities:

| Entity | Purpose |
|---|---|
| `trading_sessions` | Daily Kite auth plus mode/arming windows |
| `instruments` | Daily Kite instrument mapping |
| `watchlist_items` | Symbols allowed for scanning |
| `candles` | Completed OHLCV bars |
| `signals` | Immutable scanner candidate snapshots |
| `recommendations` | Structured AI decisions and model metadata |
| `risk_checks` | Deterministic automatic approval record and reasons |
| `orders` | Internal/broker order registry |
| `order_events` | Broker state transition audit log |
| `trades` | Fills |
| `journal_entries` | Planned versus realised trade record |
| `system_events` | Kill switch, errors and heartbeats |
| `model_runs` | Input hash, prompt version, cost/latency metadata |

Never rely on broker intraday order-history availability as the long-term journal.

## Infrastructure boundary

### Google Compute Engine VM

A single small VM is sufficient for the first personal experiment. Docker Compose runs API, worker, PostgreSQL and Redis. Assign a reserved static external IP before testing order placement. Store credentials through Secret Manager in deployment; local development uses placeholder environment values only.

P02 deploys only the OFF-mode API, PostgreSQL and Redis services. The worker process, market-data ingestion, broker authentication, OpenAI calls and execution gateway remain future phases.

### Static-IP/execution isolation

Only the Execution Gateway needs authority to call live order endpoints. In future, scanners or dashboards can move elsewhere, but live order outbound traffic remains on the VM with the registered static IP.

## OpenAI boundary

The model is invoked only after a candidate exists. It receives structured numeric/context data and an allowlisted strategy name. It does not receive tools for web search or order submission. The output is parsed against a strict schema. Parse failure, timeout or low confidence means reject or paper-log only.

## Reliability decisions

- Use completed-bar scans, not tick-by-tick AI calls.
- Persist candidate snapshots before any AI call.
- Generate idempotency keys for approved instruction and broker actions.
- Add stale-data and stale-order-instruction expiry.
- Keep new-entry loop and protective-exit monitor separate so exits continue when entries are disabled.
- Force intraday positions flat before configured cutoff.
