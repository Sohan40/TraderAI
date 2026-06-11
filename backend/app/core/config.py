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
    market_data_watchlist_file: str = ""
    market_data_mode: str = "quote"
    market_data_max_instruments: int = 10
    market_data_stale_after_seconds: int = 10
    market_data_candle_interval: str = "1minute"
    scanner_enabled: bool = False
    scanner_strategies: str = "opening_range_breakout_long,vwap_pullback_continuation_long"
    scanner_observation_mode: str = "SHADOW"
    scanner_future_live_eligible_strategy: str = "opening_range_breakout_long"
    scanner_opening_range_minutes: int = 15
    scanner_stale_after_seconds: int = 10
    scanner_min_volume_ratio: float = 1.5
    scanner_max_spread_pct: float = 0.20
    scanner_require_spread_for_future_live: bool = True
    scanner_benchmark_symbol: str = ""
    scanner_auto_loop_enabled: bool = False
    scanner_auto_loop_interval_seconds: int = 300
    scanner_auto_loop_symbols: str = ""
    scanner_auto_loop_use_market_watchlist: bool = True
    scanner_auto_loop_store_rejections: bool = False
    scanner_auto_loop_max_symbols: int = 20
    scanner_auto_loop_timeframe: str = "1minute"
    scanner_auto_loop_start_after_ist: str = "10:07"
    scanner_auto_loop_stop_after_ist: str = "15:00"
    scanner_auto_loop_run_on_market_days_only: bool = False
    scanner_auto_loop_min_candles: int = 51
    scanner_auto_loop_require_session_start: bool = True
    scanner_auto_loop_require_continuity: bool = True
    scanner_auto_loop_suppress_duplicate_rejections: bool = True
    scanner_auto_loop_candidates_always_persist: bool = True
    scanner_auto_loop_use_selected_universe: bool = False
    universe_selection_enabled: bool = False
    universe_selection_pool: str = ""
    universe_selection_pool_file: str = ""
    universe_selection_max_pool_symbols: int = 100
    universe_selection_output_limit: int = 20
    universe_selection_timeframe: str = "1minute"
    universe_selection_min_session_candles: int = 51
    universe_selection_lookback_days: int = 5
    universe_selection_require_active_instrument: bool = True
    universe_selection_require_continuity: bool = True
    universe_selection_benchmark_symbol: str = "NSE:NIFTYBEES"
    universe_selection_min_price: float = 20
    universe_selection_max_price: float = 10000
    universe_selection_min_avg_turnover: float = 0
    universe_selection_min_atr_pct: float = 0
    universe_selection_max_atr_pct: float = 10
    universe_selection_exclude_special_char_symbols: bool = True
    universe_selection_store_runs: bool = True
    universe_selection_use_latest_for_scanner_batch: bool = False
    universe_selection_stale_policy: str = "exclude"
    market_ops_automation_enabled: bool = False
    market_ops_notify_enabled: bool = False
    market_ops_notify_provider: str = "none"
    market_ops_telegram_bot_token: str = ""
    market_ops_telegram_chat_id: str = ""
    market_ops_notify_min_level: str = "warning"
    market_ops_telegram_interactive_enabled: bool = False
    market_ops_telegram_interactive_poll_seconds: float = 2
    market_ops_telegram_interactive_allowed_chat_id: str = ""
    market_ops_telegram_interactive_allowed_user_id: str = ""
    market_ops_telegram_interactive_max_actions_per_minute: int = 10
    market_ops_telegram_interactive_require_confirmation: bool = True
    market_ops_send_kite_login_link: bool = False
    market_ops_login_recovery_enabled: bool = False
    market_ops_login_recovery_start_ist: str = "09:00"
    market_ops_login_recovery_stop_ist: str = "09:25"
    market_ops_login_recovery_interval_seconds: int = 30
    market_ops_autostart_enabled: bool = False
    market_ops_timezone: str = "Asia/Kolkata"
    market_ops_preopen_check_time: str = "08:55"
    market_ops_stream_start_time: str = "09:08"
    market_ops_stream_verify_time: str = "09:16"
    market_ops_universe_select_time: str = "10:07"
    market_ops_scanner_start_time: str = "10:08"
    market_ops_scanner_interval_seconds: int = 300
    market_ops_scanner_stop_time: str = "15:00"
    market_ops_stream_stop_time: str = "15:31"
    market_ops_require_kite_session: bool = True
    market_ops_require_watchlist_ready: bool = True
    market_ops_require_stream_connected: bool = True
    market_ops_require_min_candles_for_universe: int = 51
    market_ops_use_universe_selection: bool = True
    market_ops_use_selected_universe_for_scanner: bool = True
    market_ops_store_rejections: bool = False
    market_ops_dry_run: bool = False
    market_ops_decision_auto_evaluate_enabled: bool = False
    market_ops_decision_auto_evaluate_max_signals: int = 5
    market_ops_decision_auto_evaluate_only_candidates: bool = True
    market_ops_decision_notify_enabled: bool = True
    market_ops_decision_notify_verdicts: str = "ELIGIBLE,WATCH,REJECT"
    market_ops_decision_notify_include_reasons: bool = True
    market_ops_decision_notify_include_warnings: bool = True
    openai_decision_enabled: bool = False
    openai_decision_adapter: str = "fake"
    openai_model: str = ""
    openai_api_key: str = ""
    openai_decision_timeout_seconds: float = 10
    openai_decision_max_retries: int = 1
    openai_decision_store: bool = False
    openai_decision_prompt_version: str = "p07_1_v1"
    openai_decision_min_confidence: float = 0.60
    openai_decision_max_output_tokens: int = 800
    openai_decision_evaluation_mode: str = "LIVE_SHADOW"
    max_trade_notional_inr: float = 500
    max_planned_risk_per_trade_inr: float = 10
    max_daily_loss_inr: float = 20
    paper_enabled: bool = False
    paper_mode: str = "OFF"
    paper_max_trades_per_day: int = 3
    paper_default_quantity: int = 1
    paper_entry_buffer_pct: float = 0
    paper_stop_pct: float = 0.50
    paper_target_r_multiple: float = 2.0
    paper_force_flat_time_ist: str = "15:10"
    paper_estimated_cost_per_trade: float = 0
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
