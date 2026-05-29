"""FastAPI application entrypoint for the scaffold."""

from fastapi import FastAPI

from app.api.routes import health
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(title="Zerodha AI Trader API")
app.include_router(health.router)
