# Analysis Module

Purpose: pure deterministic indicator calculations over completed stored candles.

P05 formulas:

- EMA 9/20/50: seeded with the simple average of the first period, then standard multiplier `2 / (period + 1)`.
- RSI 14: Wilder-style average gain/loss smoothing, requiring 15 closes.
- ATR 14: Wilder-style true range smoothing, requiring 15 bars.
- VWAP: typical price `(high + low + close) / 3`, weighted by completed-candle volume from regular current IST session bars only, beginning at 09:15 IST.
- Opening range: high/low for completed current-session bars in the first configured minutes after 09:15 IST, default 15.
- Previous-day high/low: best-effort high/low from the latest prior IST session present in loaded history.
- Volume ratio: latest volume divided by the average of the previous 20 completed bars, using trailing history that may cross the prior/current session boundary.
- Relative index movement: symbol percent move minus configured benchmark percent move, only when benchmark bars exist.
- Spread percentage: only from explicit quote context; never inferred from candles.

Unavailable inputs return `None` and become scanner veto context. This module performs no broker, OpenAI, scanner scheduling, or trading actions.

P05 scanner feature input is split by scope before calculation:

- trailing indicators: EMA 9/20/50, RSI 14, ATR 14 and volume ratio use trailing regular-session completed bars ending at the evaluated bar and may cross session boundaries;
- opening range and VWAP use only regular current IST session bars starting at or after 09:15 IST;
- previous-day high/low uses the most recent prior IST date with available regular-session bars;
- continuity checks reject gaps inside the regular current IST session while allowing expected overnight or pre-open-to-open gaps.

Session-based scanner candidates require explicit current-session context:

- VWAP pullback evaluation requires stored regular-session candles to begin at 09:15 IST and remain continuous through the evaluated latest bar;
- opening-range breakout evaluation requires the full configured opening-range window from 09:15 IST to be present continuously before a candidate can be emitted;
- pre-open candles are excluded and never satisfy session-start availability;
- until historical backfill exists, a scanner started late in the day emits audited data-quality rejections instead of candidates based on partial-session VWAP or opening range.
