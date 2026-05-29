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
