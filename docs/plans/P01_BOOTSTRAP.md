# P01 — Backend Bootstrap and Storage Foundation


## Objective

Create a testable FastAPI backend with PostgreSQL and Redis foundations. Trading remains impossible.

## Deliverables

- `backend/` Python project using a package manager chosen and documented.
- FastAPI app with:
  - `GET /healthz`;
  - `GET /readyz`;
  - version/status endpoint returning mode but never secrets.
- `pydantic-settings` configuration with safe defaults:
  - `TRADING_MODE=OFF`;
  - `LIVE_ARMED=false`.
- Docker Compose for local PostgreSQL and Redis.
- SQLAlchemy async session setup and Alembic.
- Initial schema for:
  - `system_events`;
  - `trading_sessions`;
  - `instruments`;
  - `candles`;
  - `signals`;
  - `recommendations`;
  - `risk_checks`;
  - `orders`;
  - `order_events`;
  - `trades`;
  - `journal_entries`;
  - `model_runs`.
- Structured JSON logging with secret/token redaction.
- Test/lint/type-check configuration.

## Safety requirements

- No Kite or OpenAI SDK call.
- No order placement routes.
- Health output cannot expose credentials or database URLs.
- A test verifies default mode is `OFF`.

## Acceptance criteria

- Containers start locally.
- Migrations apply from an empty database.
- Readiness fails meaningfully when storage is unavailable.
- Tests cover configuration safety and health endpoints.
- Lint/type checks pass.

## Codex prompt

```text
Implement only P01_BACKEND_BOOTSTRAP.

Create the FastAPI backend, Docker Compose services, configuration, SQLAlchemy/Alembic schema,
health endpoints, JSON logging and test/lint/type-check setup.

Constraints:
- No broker or OpenAI integration.
- Runtime defaults must be TRADING_MODE=OFF and LIVE_ARMED=false.
- No credentials in source.
- Add tests proving the safe defaults and health endpoint behaviour.

Run tests, lint and type checks; report commands and changed files.
```
