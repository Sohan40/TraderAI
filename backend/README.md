# Backend

The backend uses Python packaging through `pyproject.toml` with `pip` for the initial bootstrap.

P01 provides the FastAPI application, PostgreSQL/Redis connection foundations, SQLAlchemy metadata, Alembic migration scaffolding, and health/readiness tests.

P03 adds Kite authentication and session handling only. Kite auth is disabled by default and requires operator-token protection.

P04 adds read-only market-data routes for instrument sync and quote-stream lifecycle control. All market-data flags are disabled by default, use the encrypted P03 Kite session internally, and never expose tokens.

Trading remains impossible in this phase: there are no OpenAI calls, scanners, order execution code, or live-trading service.
