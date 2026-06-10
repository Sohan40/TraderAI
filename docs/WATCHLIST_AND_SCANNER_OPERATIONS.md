# Watchlist and Scanner Operations

P05.5-P05.7 add local diagnostics and operator controls around the existing
read-only market-data and deterministic scanner services. They do not add live
execution, broker order calls, OpenAI, paper replay automation, Kronos, or MCP.

All routes below require `X-Operator-Token`.

## Recommended Initial Watchlist

Start with these 20 NSE cash-equity symbols:

```text
NSE:SBIN
NSE:RELIANCE
NSE:HDFCBANK
NSE:ICICIBANK
NSE:AXISBANK
NSE:KOTAKBANK
NSE:INFY
NSE:TCS
NSE:HCLTECH
NSE:TECHM
NSE:BHARTIARTL
NSE:LT
NSE:ITC
NSE:TATAMOTORS
NSE:MARUTI
NSE:SUNPHARMA
NSE:HINDUNILVR
NSE:BAJFINANCE
NSE:NTPC
NSE:POWERGRID
```

For the environment string, join them with commas and set
`MARKET_DATA_MAX_INSTRUMENTS=20`.

An optional newline file may be selected with `MARKET_DATA_WATCHLIST_FILE`.
Blank lines and lines beginning with `#` are ignored. When both the file and
environment string are configured, the file wins and validation returns a
warning. The file path must be readable inside the API process or container.

Before expanding to 50 symbols:

1. Set `MARKET_DATA_MAX_INSTRUMENTS=50`.
2. Keep `SCANNER_AUTO_LOOP_MAX_SYMBOLS` at a deliberately reviewed limit.
3. Force-recreate the API so changed environment values are loaded.
4. Validate the watchlist.
5. Run instrument sync.
6. Validate again before starting the stream.

## Diagnostic Routes

```text
GET  /api/v1/market-data/watchlist/validate
GET  /api/v1/market-data/stream/readiness
POST /api/v1/market-data/instruments/sync
GET  /api/v1/ops/morning-readiness
```

Watchlist validation uses configuration and the local database only. It reports
format errors, duplicates, unsupported exchanges, blank entries, limits,
missing instruments, inactive instruments, and whether instrument sync or
stream start is safe.

Stream readiness also checks the configured market-data flags, supported mode,
local Kite session record, and current process-local stream status. It does not
fetch the Kite instrument dump or call a market API.

Instrument sync retains its existing count fields and adds
`watchlist_validation` after the sync, including any symbols still missing.

## Scanner Operations

```text
POST /api/v1/scanner/run-batch
POST /api/v1/scanner/auto-loop/start
POST /api/v1/scanner/auto-loop/stop
GET  /api/v1/scanner/auto-loop/status
POST /api/v1/scanner/auto-loop/run-now
```

Manual batch scanning defaults to the configured market watchlist and stores
rejections unless `store_rejections=false`. `dry_run=true` evaluates without
inserting signals. One-symbol failures are reported without stopping the rest
of the batch.

P05.8 can provide a latest selected universe. Manual batch uses it only when
`use_latest_universe=true` or its separate default setting is explicitly
enabled. Auto-loop uses it only when
`SCANNER_AUTO_LOOP_USE_SELECTED_UNIVERSE=true`. Missing selection data fails or
skips clearly; it never silently changes `MARKET_DATA_WATCHLIST`.

Keep the static watchlist as the default until enough local candles exist for
selection. A larger universe pool alone does not make symbols rankable because
P05.8 performs no historical backfill and no automatic stream subscription.

The auto loop is disabled by default. It must be explicitly enabled in config
and explicitly started through the operator route. `run-now` follows the same
strict enabled flag. The loop:

- reads completed stored candles only;
- prevents overlapping runs;
- requires the configured session context and candle continuity by default;
- skips symbols below the minimum candle count;
- persists candidates;
- does not store rejections by default;
- relies on immutable signal-key uniqueness to suppress repeated inserts;
- records its last summary and a safe last-error category in memory.

`SCANNER_AUTO_LOOP_RUN_ON_MARKET_DAYS_ONLY=false` remains the default because
this phase does not introduce a market-holiday calendar. When enabled, the
current check excludes weekends only.

## Morning Workflow

Before market, around 09:00 IST:

1. Confirm `TRADING_MODE=OFF`.
2. Confirm `LIVE_ARMED=false`.
3. Confirm `PAPER_ENABLED=false`.
4. Confirm `PAPER_MODE=OFF`.
5. Confirm the local Kite session is active and unexpired.
6. Call watchlist validation.
7. If symbols are missing or inactive, run instrument sync.
8. Validate the watchlist again.
9. If environment values changed, force-recreate the API.
10. Start the market stream around 09:08-09:12 IST.
11. Confirm `connected=true` and subscribed symbols match configured symbols.
12. Do not deploy or restart after the stream starts.

`docker compose restart api` does not reload changed environment variables.
After environment changes use:

```text
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml up -d --force-recreate api
```

After 10:07 IST:

1. Run a scanner batch or explicitly start the auto loop.
2. Confirm candidate, rejection, duplicate, skip, and error counts.
3. Do not trigger paper replay during market hours unless deliberately testing
   and no restart is needed.

After market:

1. Stop the market stream.
2. Run P06 paper replay deliberately.
3. Turn paper mode off.
4. Back up the database if needed.
5. Review paper and scanner reports.

Adding symbols requires both instrument sync and an API force-recreate when
environment configuration changed. Validate before market open rather than
discovering the mismatch during stream start.
