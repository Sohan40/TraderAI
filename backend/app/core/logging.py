"""Structured logging with basic secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any


SECRET_KEY_PATTERN = (
    r"(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|api[_-]?secret|access[_-]?token|request[_-]?token|operator[_-]?auth[_-]?token|"
    r"session[_-]?encryption[_-]?key|openai[_-]?api[_-]?key|password|secret|token|checksum)"
)
SECRET_PATTERN = re.compile(rf"(?i)\b({SECRET_KEY_PATTERN})\b")
SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"(?i)\b({SECRET_KEY_PATTERN})\b\s*[:=]\s*([^,\s}}]+)"
)
URL_PASSWORD_PATTERN = re.compile(r"://([^:/@\s]+):([^@\s]+)@")
REDACTED = "[REDACTED]"


def redact_secret(value: Any) -> Any:
    """Redact likely secret values in strings, mappings, and sequences."""
    if isinstance(value, dict):
        return {
            key: REDACTED if SECRET_PATTERN.search(str(key)) else redact_secret(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secret(item) for item in value]
    if isinstance(value, str):
        value = URL_PASSWORD_PATTERN.sub(r"://\1:[REDACTED]@", value)
        return SECRET_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    return value


class JsonFormatter(logging.Formatter):
    """Emit compact JSON logs using only the standard library."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secret(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = "INFO") -> None:
    """Configure standard-library JSON logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    logging.basicConfig(
        handlers=[handler],
        level=level.upper(),
        force=True,
    )
