"""Health and status endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.health import check_database, check_redis

router = APIRouter()


@router.get("/")
def read_root() -> dict[str, str]:
    """Return non-sensitive application status."""
    return {
        "project": "zerodha-ai-trader",
        "status": "bootstrap",
        "trading_mode": settings.trading_mode,
    }


@router.get("/healthz")
def read_health() -> dict[str, str]:
    """Return basic process health."""
    return {"status": "healthy"}


@router.get("/readyz")
async def read_readiness() -> JSONResponse:
    """Return dependency readiness without exposing connection details."""
    database_ok = await check_database()
    redis_ok = await check_redis()
    ready = database_ok and redis_ok

    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if ready else "not_ready",
            "dependencies_checked": True,
            "dependencies": {
                "database": "ok" if database_ok else "unavailable",
                "redis": "ok" if redis_ok else "unavailable",
            },
        },
    )
