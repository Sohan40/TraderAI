"""FastAPI application entrypoint for the scaffold."""

from fastapi import FastAPI

from app.api.routes import health, kite_auth, market_data
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(title="Zerodha AI Trader API")
app.include_router(health.router)
app.include_router(kite_auth.router)
app.include_router(market_data.router)
