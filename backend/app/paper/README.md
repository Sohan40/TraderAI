# Paper Trading Module

Purpose: deterministic P06 paper trading over persisted P05 `CANDIDATE` signals and completed stored candles only.

Safety boundaries:

- Defaults are `PAPER_ENABLED=false` and `PAPER_MODE=OFF`.
- `OFF` and `SHADOW` do not create paper orders or fills.
- `PAPER` creates simulated rows only.
- `LIVE` raises a disabled/not-implemented error.
- Paper code does not import Kite, OpenAI, Kronos or MCP modules.

Fill assumptions:

- Long-only.
- Uses completed `1minute` candles only.
- Entry is a simulated limit buy using the signal candle close plus `PAPER_ENTRY_BUFFER_PCT`.
- Entry fills only on a future same-session candle when `low <= entry_price <= high`.
- Stop is `entry * (1 - PAPER_STOP_PCT / 100)`.
- Target is `entry + PAPER_TARGET_R_MULTIPLE * (entry - stop)`.
- Stop is hit when a later candle low is at or below stop.
- Target is hit when a later candle high is at or above target.
- If stop and target touch in the same candle, stop wins for long trades.
- If replay reaches `PAPER_FORCE_FLAT_TIME_IST`, the trade exits at that candle close with `FORCE_FLAT`.
- If replay ends before force-flat and no stop/target hits, the trade exits at the last available later candle close with `TIME_EXIT`.
- If an entry fills but there are no later candles, the outcome is `DATA_ENDED` and no exit price is invented.
- Estimated cost is `PAPER_ESTIMATED_COST_PER_TRADE` and is subtracted from gross P&L only for filled trades with an exit price.

CLI:

```text
python -m app.paper.replay --symbol NSE:SBIN --from 2026-06-03T03:45:00Z --to 2026-06-03T09:45:00Z --enable-paper
```

The CLI reads stored P05 signals and candles through the local database configuration. It never calls Kite, OpenAI, Kronos, MCP or any live execution gateway.
