# Scanners Module

Purpose: deterministic P05 observations over completed stored candles only.

Implemented strategies:

- `opening_range_breakout_long`
- `vwap_pullback_continuation_long`

The scanner emits immutable `CANDIDATE` or `REJECTED_SIGNAL` records with feature snapshots and veto reasons. It never creates order instructions, quantities, paper fills, broker calls, OpenAI calls, Kronos calls, or MCP calls.

Execution is disabled by default with `SCANNER_ENABLED=false` and must be operator-triggered.
