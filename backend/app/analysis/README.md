# Analysis Module

Purpose: pure deterministic indicator calculations over completed stored candles.

P05 formulas:

- EMA 9/20/50: seeded with the simple average of the first period, then standard multiplier `2 / (period + 1)`.
- RSI 14: Wilder-style average gain/loss smoothing, requiring 15 closes.
- ATR 14: Wilder-style true range smoothing, requiring 15 bars.
- VWAP: typical price `(high + low + close) / 3`, weighted by completed-candle volume.
- Opening range: high/low for completed bars in the first configured minutes after 09:15 IST, default 15.
- Previous-day high/low: latest prior IST session when available.
- Volume ratio: latest volume divided by the average of the previous 20 completed bars.
- Relative index movement: symbol percent move minus configured benchmark percent move, only when benchmark bars exist.
- Spread percentage: only from explicit quote context; never inferred from candles.

Unavailable inputs return `None` and become scanner veto context. This module performs no broker, OpenAI, scanner scheduling, or trading actions.
