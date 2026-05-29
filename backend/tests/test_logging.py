import json
import logging

from app.core.logging import JsonFormatter, REDACTED, redact_secret


def test_redact_secret_masks_mapping_values_and_url_passwords() -> None:
    redacted = redact_secret(
        {
            "api_key": "real-value",
            "database_url": "postgresql+asyncpg://trader:change-me@postgres:5432/trader",
            "nested": {"access_token": "token-value"},
        }
    )

    assert redacted["api_key"] == REDACTED
    assert redacted["nested"]["access_token"] == REDACTED
    assert "change-me" not in redacted["database_url"]


def test_json_formatter_redacts_secret_assignments() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="KITE_API_SECRET=abc123",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["message"] == f"KITE_API_SECRET={REDACTED}"
    assert "abc123" not in payload["message"]
