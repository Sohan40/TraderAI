# Analysis Module

Purpose: pure deterministic indicator calculations over completed stored candles.

P05 formulas:

- EMA 9/20/50: seeded with the simple average of the first period, then standard multiplier `2 / (period + 1)`.
- RSI 14: Wilder-style average gain/loss smoothing, requiring 15 closes.
- ATR 14: Wilder-style true range smoothing, requiring 15 bars.
- VWAP: typical price `(high + low + close) / 3`, weighted by completed-candle volume from the current IST session only, beginning at 09:15 IST.
- Opening range: high/low for completed current-session bars in the first configured minutes after 09:15 IST, default 15.
- Previous-day high/low: best-effort high/low from the latest prior IST session present in loaded history.
- Volume ratio: latest volume divided by the average of the previous 20 completed bars, using trailing history that may cross the prior/current session boundary.
- Relative index movement: symbol percent move minus configured benchmark percent move, only when benchmark bars exist.
- Spread percentage: only from explicit quote context; never inferred from candles.

Unavailable inputs return `None` and become scanner veto context. This module performs no broker, OpenAI, scanner scheduling, or trading actions.

P05 scanner feature input is split by scope before calculation:

- trailing indicators: EMA 9/20/50, RSI 14, ATR 14 and volume ratio use the trailing completed bars ending at the evaluated bar and may cross session boundaries;
- opening range and VWAP use only the current IST session;
- previous-day high/low uses the most recent prior IST session available in loaded candles;
- continuity checks reject gaps inside the current IST session while allowing expected overnight gaps across sessions.
