# Backend

The backend uses Python packaging through `pyproject.toml` with `pip` for the initial bootstrap.

P01 provides the FastAPI application, PostgreSQL/Redis connection foundations, SQLAlchemy metadata, Alembic migration scaffolding, and health/readiness tests.

P03 adds Kite authentication and session handling only. Kite auth is disabled by default and requires operator-token protection.

P04 adds read-only market-data routes for instrument sync and quote-stream lifecycle control. All market-data flags are disabled by default, use the encrypted P03 Kite session internally, and never expose tokens.

P05 adds deterministic indicators and scanner observations over completed stored candles only. Scanner execution is disabled by default and operator-triggered; it emits only immutable `CANDIDATE` or `REJECTED_SIGNAL` records.

P05.5-P05.7 add DB-only watchlist and stream-readiness diagnostics, deterministic multi-symbol batch scanning, a disabled-by-default operator-started scanner auto loop, and an aggregated morning-readiness route. The scanner operations use stored completed candles only.

P05.8 adds deterministic universe-pool validation, transparent local-candle
scoring, compact persisted selection runs, and opt-in scanner integration.

P05.9 adds a disabled-by-default process-local market-operations scheduler,
operator one-shot controls, and optional Telegram notifications. It coordinates
existing readiness, read-only stream, universe, and scanner services only.

P06 adds a disabled-by-default deterministic paper engine and journal. It consumes persisted P05 `CANDIDATE` records, simulates long-only limit entries, stop/target/time/force-flat exits over completed one-minute candles, and stores clearly simulated order/event/trade/journal rows.

P07 adds disabled-by-default, operator-triggered structured decision evaluation
with fake and OpenAI Responses API adapters. It stores model runs and
recommendations only. Existing verdicts may appear in paper reports but never
gate or trigger replay.

P07.1 optionally evaluates newly persisted scanner candidates after a
market-ops batch when both decision gates are enabled. Operator diagnostics are
available at `GET /api/v1/decision/auto-status` and bounded manual recovery at
`POST /api/v1/decision/evaluate-latest?limit=5`. Telegram remains
notification-only, and neither path invokes P06 replay.

Live trading remains impossible: there is no real broker order gateway, and
`LIVE` paper mode raises a disabled/not-implemented error.
