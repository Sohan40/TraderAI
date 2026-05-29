# OpenAI Decision Agent Contracts

## Design rule

The model is not a market-data source and not an execution authority. It is a structured evaluator of a deterministic candidate generated from Kite-derived data. No web-search tool is configured in the MVP.

## Decision input schema

```json
{
  "candidate_id": "uuid",
  "symbol": "NSE:EXAMPLE",
  "strategy": "opening_range_breakout_long",
  "timestamp_ist": "2026-06-01T10:05:00+05:30",
  "market_data_age_seconds": 0.4,
  "features": {
    "last_price": 0,
    "entry_trigger": 0,
    "vwap": 0,
    "ema_9": 0,
    "ema_20": 0,
    "ema_50": 0,
    "rsi_14": 0,
    "atr_14": 0,
    "volume_ratio": 0,
    "spread_pct": 0,
    "index_change_pct": 0
  },
  "session_state": {
    "available_cash": 0,
    "open_positions": 0,
    "trades_today": 0,
    "daily_realized_pnl": 0
  },
  "limits": {
    "max_trade_notional": 500,
    "max_planned_risk": 10,
    "max_daily_loss": 20
  }
}
```

## Decision output schema

```json
{
  "verdict": "ELIGIBLE",
  "strategy_template": "opening_range_breakout_long",
  "confidence": 0.0,
  "reasons": ["string"],
  "warnings": ["string"],
  "recommended_stop_method": "breakout_failure_or_atr",
  "recommended_target_r_multiple": 1.5,
  "data_sufficiency": "SUFFICIENT"
}
```

Allowed verdicts: `ELIGIBLE`, `WATCH`, `REJECT`. Allowed templates are configured server-side.

## System prompt

```text
You are the Trade Decision Agent for a personal experimental Indian cash-equity system.

You receive a deterministic scanner candidate and structured technical/account context.
You do not have internet access and must not claim knowledge of company news, results,
fundamentals, announcements, or external events.

Your role is conservative evaluation:
- Return REJECT when data is insufficient, stale, inconsistent or weak.
- Select only one of the supplied allowlisted strategy templates.
- Never determine order quantity.
- Never construct broker API requests.
- Never override risk limits.
- Never request leverage, F&O, short selling, overnight holding, averaging down or martingale sizing.

Return only JSON matching the provided schema.
```

## Validation policy

The application must:

- validate JSON schema and enums;
- reject any non-allowlisted template;
- reject output containing external-fact claims;
- store prompt version, input hash, model name, latency and parsed output;
- send only eligible schema-valid output to the deterministic risk engine;
- treat model failures as no-trade.
