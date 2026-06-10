"""Secret-safe market-operations notifications."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import error, parse, request

from app.core.config import Settings

LEVELS = {"info": 10, "warning": 20, "error": 30}
MAX_MESSAGE_LENGTH = 3500
TELEGRAM_API_ROOT = "https://api.telegram.org"
_SECRET_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "database_url",
    "redis_url",
    "api_key",
    "chat_id",
    "operator",
    "payload",
    "raw_env",
)


@dataclass(frozen=True)
class NotificationResult:
    ok: bool
    skipped: bool
    provider: str
    event: str
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "provider": self.provider,
            "event": self.event,
            "error": self.error,
        }


HttpSender = Callable[[str, bytes, float], None]


class Notifier:
    """Send bounded plain-text notifications without exposing credentials."""

    def __init__(
        self,
        *,
        settings: Settings,
        http_sender: HttpSender | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._http_sender = http_sender or _post
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def notify(
        self,
        *,
        level: str,
        event: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> NotificationResult:
        provider = self._settings.market_ops_notify_provider.strip().lower()
        normalized_level = level.strip().lower()
        if normalized_level not in LEVELS:
            return NotificationResult(False, True, provider, event, "invalid_level")
        if not self._settings.market_ops_notify_enabled or provider == "none":
            return NotificationResult(True, True, provider, event)
        minimum = self._settings.market_ops_notify_min_level.strip().lower()
        if minimum not in LEVELS:
            return NotificationResult(False, True, provider, event, "invalid_min_level")
        if LEVELS[normalized_level] < LEVELS[minimum]:
            return NotificationResult(True, True, provider, event)
        if provider != "telegram":
            return NotificationResult(False, True, provider, event, "unsupported_provider")
        token = self._settings.market_ops_telegram_bot_token
        chat_id = self._settings.market_ops_telegram_chat_id
        if not token or not chat_id:
            return NotificationResult(False, True, provider, event, "telegram_not_configured")

        text = _format_message(
            level=normalized_level,
            event=event,
            message=message,
            timestamp=self._now_provider(),
            details=_safe_details(
                details or {},
                secrets=_configured_secrets(self._settings),
            ),
        )
        payload = parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        url = f"{TELEGRAM_API_ROOT}/bot{token}/sendMessage"
        try:
            await asyncio.to_thread(self._http_sender, url, payload, 5.0)
        except Exception:
            return NotificationResult(False, False, provider, event, "telegram_send_failed")
        return NotificationResult(True, False, provider, event)

    async def test_notification(self) -> NotificationResult:
        return await self.notify(
            level="warning",
            event="market_ops_test_notification",
            message="TraderAI market operations notification test.",
            details={"automation_enabled": self._settings.market_ops_automation_enabled},
        )


def _post(url: str, payload: bytes, timeout: float) -> None:
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read(2048)
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("telegram_send_failed") from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("telegram_invalid_response") from exc
    if not parsed.get("ok"):
        raise RuntimeError("telegram_rejected_message")


def _safe_details(
    details: dict[str, object],
    *,
    secrets: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        key: _safe_value(value, secrets=secrets)
        for key, value in details.items()
        if not any(fragment in key.lower() for fragment in _SECRET_FRAGMENTS)
    }


def _safe_value(value: object, *, secrets: tuple[str, ...]) -> object:
    if isinstance(value, dict):
        return _safe_details(value, secrets=secrets)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        safe = value
        for secret in secrets:
            safe = safe.replace(secret, "[redacted]")
        return safe
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _configured_secrets(settings: Settings) -> tuple[str, ...]:
    values = (
        settings.market_ops_telegram_bot_token,
        settings.market_ops_telegram_chat_id,
        settings.operator_auth_token,
        settings.kite_api_key,
        settings.kite_api_secret,
        settings.kite_session_encryption_key,
        settings.openai_api_key,
        settings.database_url,
        settings.redis_url,
    )
    return tuple(value for value in values if value)


def _format_message(
    *,
    level: str,
    event: str,
    message: str,
    timestamp: datetime,
    details: dict[str, object],
) -> str:
    normalized = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    lines = [
        f"TraderAI {level}",
        f"event: {event}",
        f"time: {normalized.astimezone(timezone.utc).isoformat()}",
        "",
        message,
    ]
    if details:
        lines.extend(["", "details:"])
        lines.extend(f"- {key}: {value}" for key, value in sorted(details.items()))
    text = "\n".join(lines)
    return text[:MAX_MESSAGE_LENGTH]
