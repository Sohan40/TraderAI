# Backend

The backend uses Python packaging through `pyproject.toml` with `pip` for the initial bootstrap.

P01 provides the FastAPI application, PostgreSQL/Redis connection foundations, SQLAlchemy metadata, Alembic migration scaffolding, and health/readiness tests.

Trading remains impossible in this phase: there are no broker routes, no OpenAI calls, no order execution code, and no live-trading service.
