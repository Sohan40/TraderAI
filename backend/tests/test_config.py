from app.core.config import Settings


def test_settings_default_to_non_live_mode() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.trading_mode == "OFF"
    assert settings.live_armed is False


def test_settings_keep_kite_auth_disabled_by_default() -> None:
    settings = Settings()

    assert settings.kite_auth_enabled is False
    assert settings.kite_api_key == ""
    assert settings.kite_api_secret == ""
    assert settings.kite_redirect_url == ""
    assert settings.kite_session_encryption_key == ""
    assert settings.operator_auth_token == ""


def test_operational_automation_defaults_remain_disabled() -> None:
    settings = Settings()

    assert settings.market_data_watchlist_file == ""
    assert settings.scanner_auto_loop_enabled is False
    assert settings.scanner_auto_loop_store_rejections is False
    assert settings.paper_enabled is False
    assert settings.paper_mode == "OFF"
    assert settings.universe_selection_enabled is False
    assert settings.universe_selection_use_latest_for_scanner_batch is False
    assert settings.universe_selection_stale_policy == "exclude"
    assert settings.scanner_auto_loop_use_selected_universe is False
    assert settings.market_ops_automation_enabled is False
    assert settings.market_ops_notify_enabled is False
    assert settings.market_ops_notify_provider == "none"
    assert settings.market_ops_telegram_interactive_enabled is False
    assert settings.market_ops_telegram_interactive_allowed_chat_id == ""
    assert settings.market_ops_telegram_interactive_allowed_user_id == ""
    assert settings.market_ops_telegram_interactive_max_actions_per_minute == 10
    assert settings.market_ops_telegram_interactive_require_confirmation is True
    assert settings.market_ops_send_kite_login_link is False
    assert settings.market_ops_login_recovery_enabled is False
    assert settings.market_ops_autostart_enabled is False
    assert settings.openai_decision_enabled is False
    assert settings.openai_decision_adapter == "fake"
    assert settings.openai_decision_store is False
    assert settings.openai_decision_prompt_version == "p07_1_v1"
    assert settings.openai_decision_evaluation_mode == "LIVE_SHADOW"
    assert settings.market_ops_decision_auto_evaluate_enabled is False
    assert settings.market_ops_decision_auto_evaluate_max_signals == 5
    assert settings.market_ops_decision_auto_evaluate_only_candidates is True
    assert settings.market_ops_decision_notify_enabled is True
