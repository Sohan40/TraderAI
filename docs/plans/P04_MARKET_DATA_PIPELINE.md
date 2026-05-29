# P04 — Kite Market Data and Completed Candles


## Objective

Ingest live Kite market data and build stable completed bars. This is read-only; there is still no order path.

## Deliverables

- Daily instrument-sync job storing relevant mapping and tick sizes.
- Watchlist allowlist data access layer and admin-only seed command.
- Historical candle backfill adapter when available under the subscribed Kite plan.
- Kite WebSocket consumer using the official SDK where practical.
- Subscribe only to allowlisted instruments; start with configurable small maximum.
- Modes:
  - quote/LTP for regular tracking;
  - full depth only when needed for scanner spread checks.
- One-minute and five-minute candle aggregation.
- Completed candle persistence with deduplication.
- Heartbeat/state persisted to Redis and summarized in `system_events`.
- Read-only status endpoints for stream health and last completed bars.

## Safety requirements

- No order endpoints.
- Do not scan or call OpenAI yet.
- Do not log raw sensitive session tokens.
- Worker must reconnect with backoff and visibly mark data stale on loss.

## Tests

- Instrument sync parsing and upsert.
- Tick-to-candle aggregation boundaries and IST/UTC correctness.
- Duplicate/reordered tick handling.
- Heartbeat stale/healthy transitions.
- Reconnect handler with fake WebSocket stream.

## Acceptance criteria

- During a live data session, the database contains correct completed bars for the configured allowlist.
- Status visibly turns stale when the fake/live stream disconnects.
- Restart does not duplicate bars.

## Codex prompt

```text
Implement only P04_MARKET_DATA_PIPELINE.

Add read-only instrument sync, watchlist storage, historical adapter, Kite WebSocket consumer,
1m/5m bar aggregation, heartbeat health, and tests using fake data.

No scanner, no OpenAI and no order functions.
Prefer official SDK integration behind an interface and keep all tests offline.
```
