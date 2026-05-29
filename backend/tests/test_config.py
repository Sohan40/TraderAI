from app.core.config import Settings


def test_settings_default_to_non_live_mode() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.trading_mode == "OFF"
    assert settings.live_armed is False


def test_settings_do_not_model_external_credentials() -> None:
    settings = Settings()
    dumped = settings.model_dump()

    assert "kite_api_key" not in dumped
    assert "kite_api_secret" not in dumped
    assert "openai_api_key" not in dumped
