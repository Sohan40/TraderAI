from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app


client = TestClient(app)


def test_root_reports_scaffold_status_and_safe_trading_mode() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "project": "zerodha-ai-trader",
        "status": "bootstrap",
        "trading_mode": "OFF",
    }
    assert "DATABASE_URL" not in response.text
    assert "REDIS_URL" not in response.text


def test_healthz_reports_healthy() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readyz_reports_ready_when_storage_checks_pass(monkeypatch) -> None:
    async def healthy() -> bool:
        return True

    monkeypatch.setattr(health, "check_database", healthy)
    monkeypatch.setattr(health, "check_redis", healthy)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies_checked": True,
        "dependencies": {
            "database": "ok",
            "redis": "ok",
        },
    }


def test_readyz_fails_meaningfully_when_storage_is_unavailable(monkeypatch) -> None:
    async def database_down() -> bool:
        return False

    async def redis_healthy() -> bool:
        return True

    monkeypatch.setattr(health, "check_database", database_down)
    monkeypatch.setattr(health, "check_redis", redis_healthy)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies_checked": True,
        "dependencies": {
            "database": "unavailable",
            "redis": "ok",
        },
    }
