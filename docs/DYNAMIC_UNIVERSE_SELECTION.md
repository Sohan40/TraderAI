# Dynamic Universe Selection

Dynamic universe selection ranks NSE cash-equity symbols before deterministic
P05 scanning. It is a prioritization tool, not a return forecast.

## Data Requirements

The selector uses only completed candles and instrument metadata already stored
locally. It does not fetch historical data, news, fundamentals, websites, or
external market data.

Without historical backfill, a symbol can be ranked only after the system has
collected enough candles for it. Configuring a symbol in the universe pool does
not create data for that symbol and does not add it to the live stream.

## Pool Sources

Pool source precedence:

1. Request symbols supplied to the select operation.
2. `UNIVERSE_SELECTION_POOL_FILE`.
3. `UNIVERSE_SELECTION_POOL`.
4. `MARKET_DATA_WATCHLIST` fallback.

Files are newline-based. Blank lines and `#` comments are ignored. The current
MVP accepts NSE symbols only and can exclude trading symbols containing special
characters.

## Scoring

Hard exclusions are applied before ranking: missing/inactive instruments,
insufficient candles, missing session start, required continuity failure,
price and turnover bounds, ATR percentage bounds, and unsupported timeframes.
Stale candles follow `UNIVERSE_SELECTION_STALE_POLICY`, whose safe default is
`exclude`. The allowed values are:

- `exclude`: omit stale symbols from selection.
- `warn`: retain stale symbols and add the `stale_data` warning.
- `ignore`: retain stale symbols without a stale-data warning.

Use `stale_policy=exclude` for an intraday live universe. For deliberate
after-market trailing-data analysis, call selection with
`use_current_session=false&stale_policy=warn`.

The score is bounded to 100 points:

| Component | Maximum | Formula |
|---|---:|---|
| Liquidity | 15 | Average candle turnover scaled to INR 1,000,000 |
| Volatility | 15 | ATR percentage proximity to a neutral 1.5% center |
| Relative volume | 15 | Current session volume versus prior-session volume, capped at 2x |
| Trend | 20 | Above VWAP, EMA9 above EMA20, positive return from open, positive EMA20 slope |
| Breakout readiness | 20 | Near opening-range high, above prior high, volume expansion, aligned trend |
| Data quality | 15 | Awarded only when no hard exclusion exists |

Metrics unavailable from the stored data become warnings where safe. Missing
benchmark candles disable relative-strength output and add
`benchmark_missing`; they do not invent a value.

## Operator Flow

1. Maintain a reviewed universe pool.
2. Stream and collect candles for those symbols through separately configured
   market-data operations.
3. Run selection after enough candles exist.
4. Review `/api/v1/universe/latest`.
5. Explicitly run scanner batch with `use_latest_universe=true`, or separately
   enable selected-universe auto-loop use.
6. Run P06 replay deliberately after market.
7. Compare persisted selections across days.

The selector never updates `MARKET_DATA_WATCHLIST`.

## Routes

All routes require `X-Operator-Token`.

```text
GET  /api/v1/universe/status
GET  /api/v1/universe/pool/validate?symbols=NSE:SBIN&symbols=NSE:INFY
POST /api/v1/universe/select
GET  /api/v1/universe/latest
GET  /api/v1/universe/runs
GET  /api/v1/universe/runs/{run_id}
```

Future work: P04.5 or P05.9 may add a reviewed read-only historical backfill
pipeline for broader pre-market ranking.
