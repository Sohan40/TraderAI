# Backend

The backend uses Python packaging through `pyproject.toml` with `pip` for the initial bootstrap.

P01 provides the FastAPI application, PostgreSQL/Redis connection foundations, SQLAlchemy metadata, Alembic migration scaffolding, and health/readiness tests.

P03 adds Kite authentication and session handling only. Kite auth is disabled by default and requires operator-token protection.

Trading remains impossible in this phase: there are no market-data routes, OpenAI calls, order execution code, or live-trading service.
