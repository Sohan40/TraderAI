# Backend

The backend uses Python packaging through `pyproject.toml` with `pip` for the initial bootstrap.

P01 provides the FastAPI application, PostgreSQL/Redis connection foundations, SQLAlchemy metadata, Alembic migration scaffolding, and health/readiness tests.

P03 adds Kite authentication and session handling only. Kite auth is disabled by default and requires operator-token protection.

P04 adds read-only market-data routes for instrument sync and quote-stream lifecycle control. All market-data flags are disabled by default, use the encrypted P03 Kite session internally, and never expose tokens.

P05 adds deterministic indicators and scanner observations over completed stored candles only. Scanner execution is disabled by default and operator-triggered; it emits only immutable `CANDIDATE` or `REJECTED_SIGNAL` records.

Trading remains impossible in this phase: there are no OpenAI calls, order execution code, paper fills, or live-trading service.
