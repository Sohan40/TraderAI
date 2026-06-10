"""FastAPI application entrypoint for the scaffold."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import dependencies
from app.api.routes import (
    health,
    kite_auth,
    market_data,
    market_ops,
    ops,
    paper,
    scanner,
    universe,
)
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Optionally start one process-local scheduler and always stop it cleanly."""
    scheduler = None
    if settings.market_ops_autostart_enabled and settings.market_ops_automation_enabled:
        scheduler = await dependencies.get_market_ops_scheduler()
        await scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


app = FastAPI(title="Zerodha AI Trader API", lifespan=lifespan)
app.include_router(health.router)
app.include_router(kite_auth.router)
app.include_router(market_data.router)
app.include_router(scanner.router)
app.include_router(paper.router)
app.include_router(ops.router)
app.include_router(universe.router)
app.include_router(market_ops.router)
