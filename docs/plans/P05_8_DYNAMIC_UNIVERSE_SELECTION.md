# P05.8 Dynamic Universe Selection

## Scope

P05.8 is a deterministic pre-scanner filter. It ranks configured NSE cash
symbols using completed candles already stored in PostgreSQL and recommends a
bounded scan universe.

It does not guarantee returns. It does not call OpenAI, use web search, inspect
news or fundamentals, place orders, trigger paper replay, start or stop market
streaming, or mutate `MARKET_DATA_WATCHLIST`.

## Data Boundary

Only locally stored completed `1minute` candles and local instrument metadata
are used. Symbols without enough candles are excluded with reasons. If the
system has only streamed the static market watchlist, only those symbols can be
ranked.

Historical candle backfill for a broader pre-market NSE universe is explicitly
deferred to P04.5 or P05.9.

## Output

Each run records:

- validated pool membership;
- included and excluded symbols;
- transparent component scores and metrics;
- the selected top N symbols;
- the non-secret configuration snapshot;
- warnings and errors.

Scanner batch and auto-loop integration are both disabled by default and require
separate explicit settings or query parameters.
