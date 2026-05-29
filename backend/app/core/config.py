"""Safe runtime configuration defaults."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with safe non-live defaults.

    Broker and OpenAI credentials are intentionally not modeled in P01.
    """

    app_env: str = "development"
    app_timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"
    trading_mode: str = "OFF"
    live_armed: bool = False
    kite_auth_enabled: bool = False
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_redirect_url: str = ""
    kite_session_encryption_key: str = ""
    operator_auth_token: str = ""
    market_data_enabled: bool = False
    instrument_sync_enabled: bool = False
    kite_websocket_enabled: bool = False
    market_data_watchlist: str = "NSE:NIFTYBEES,NSE:SBIN"
    market_data_mode: str = "quote"
    market_data_max_instruments: int = 10
    market_data_stale_after_seconds: int = 10
    market_data_candle_interval: str = "1minute"
    app_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("API_HOST", "APP_HOST"),
    )
    app_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("API_PORT", "APP_PORT"),
    )
    database_url: str = "postgresql+asyncpg://trader:change-me@postgres:5432/trader"
    redis_url: str = "redis://:change-me@redis:6379/0"

    model_config = SettingsConfigDict(case_sensitive=False, env_file=None, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application use."""
    return Settings()


settings = get_settings()
