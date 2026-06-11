"""Disabled-by-default private Telegram long-polling operator bot."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib import error, request

from app.core.config import Settings
from app.ops.telegram_actions import TelegramActionResponse, TelegramActionService

MAX_TELEGRAM_TEXT = 3500

TelegramSender = Callable[[str, dict[str, object], float], dict[str, object]]


class TelegramInteractiveBot:
    """Poll private Telegram updates and dispatch static allowlisted actions."""

    def __init__(
        self,
        *,
        settings: Settings,
        actions: TelegramActionService,
        sender: TelegramSender | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._actions = actions
        self._sender = sender or _telegram_request
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._offset: int | None = None
        self._action_times: deque[datetime] = deque()
        self._last_update_at: datetime | None = None
        self._last_error: str | None = None
        self._last_action: str | None = None
        self._handled_updates = 0
        self._rejected_updates = 0

    async def start(self) -> dict[str, object]:
        if not self._configured():
            return self.status()
        async with self._lifecycle_lock:
            if self._task is None or self._task.done():
                try:
                    await self._discard_pending_updates()
                except Exception:
                    self._last_error = "telegram_poll_failed"
                self._task = asyncio.create_task(self._loop(), name="telegram-ops-bot")
        return self.status()

    async def stop(self) -> dict[str, object]:
        async with self._lifecycle_lock:
            task = self._task
            self._task = None
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        return self.status()

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._settings.market_ops_telegram_interactive_enabled,
            "running": self._task is not None and not self._task.done(),
            "provider": self._settings.market_ops_notify_provider,
            "allowed_chat_configured": bool(
                self._settings.market_ops_telegram_interactive_allowed_chat_id
            ),
            "allowed_user_configured": bool(
                self._settings.market_ops_telegram_interactive_allowed_user_id
            ),
            "last_update_at": (
                self._last_update_at.isoformat() if self._last_update_at else None
            ),
            "last_error": self._last_error,
            "handled_updates": self._handled_updates,
            "rejected_updates": self._rejected_updates,
            "last_action": self._last_action,
        }

    async def handle_update(self, update: dict[str, object]) -> None:
        self._last_update_at = self._now()
        message = update.get("message")
        callback = update.get("callback_query")
        if isinstance(message, dict):
            await self._handle_message(message)
            return
        if isinstance(callback, dict):
            await self._handle_callback(callback)
            return
        self._rejected_updates += 1

    async def _handle_message(self, message: dict[str, object]) -> None:
        if not self._authorized(message.get("chat"), message.get("from")):
            self._rejected_updates += 1
            return
        text = str(message.get("text", "")).strip()
        if text not in {"/start", "/menu", "/help"}:
            self._rejected_updates += 1
            return
        response = self._actions.help() if text == "/help" else self._actions.menu()
        await self._send_response(response)
        self._handled_updates += 1
        self._last_action = text

    async def _handle_callback(self, callback: dict[str, object]) -> None:
        message = callback.get("message")
        safe_message = message if isinstance(message, dict) else {}
        if not self._authorized(safe_message.get("chat"), callback.get("from")):
            self._rejected_updates += 1
            return
        callback_id = str(callback.get("id", ""))
        action = str(callback.get("data", ""))
        if not action.startswith("ops:"):
            self._rejected_updates += 1
            await self._answer_callback(callback_id, "Unknown action.")
            return
        if not self._rate_allowed():
            self._rejected_updates += 1
            await self._answer_callback(callback_id, "Rate limit reached.")
            return
        try:
            response = await self._actions.handle(action)
        except Exception:
            self._last_error = "telegram_action_failed"
            response = TelegramActionResponse(
                "Action failed safely. Check local operator status before retrying."
            )
        if response is None:
            self._rejected_updates += 1
            await self._answer_callback(callback_id, "Unknown action.")
            return
        await self._answer_callback(callback_id, "Processed.")
        await self._send_response(response)
        self._handled_updates += 1
        self._last_action = action

    async def _loop(self) -> None:
        while True:
            try:
                updates = await self._get_updates()
                for update in updates:
                    update_id = _as_int(update.get("update_id"))
                    self._offset = max(self._offset or 0, update_id + 1)
                    await self.handle_update(update)
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error = "telegram_poll_failed"
            await asyncio.sleep(max(0.1, self._settings.market_ops_telegram_interactive_poll_seconds))

    async def _discard_pending_updates(self) -> None:
        response = await self._call("getUpdates", {"offset": -1, "timeout": 0})
        updates = response.get("result", [])
        if isinstance(updates, list) and updates:
            latest = updates[-1]
            if isinstance(latest, dict):
                self._offset = _as_int(latest.get("update_id")) + 1

    async def _get_updates(self) -> list[dict[str, object]]:
        poll_timeout = max(
            1,
            min(int(self._settings.market_ops_telegram_interactive_poll_seconds), 5),
        )
        payload: dict[str, object] = {"timeout": poll_timeout}
        if self._offset is not None:
            payload["offset"] = self._offset
        response = await self._call("getUpdates", payload)
        result = response.get("result", [])
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    async def _send_response(self, response: TelegramActionResponse) -> None:
        payload: dict[str, object] = {
            "chat_id": self._settings.market_ops_telegram_interactive_allowed_chat_id,
            "text": response.text[:MAX_TELEGRAM_TEXT],
        }
        if response.keyboard:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {"text": label, "callback_data": action}
                        for label, action in row
                    ]
                    for row in response.keyboard
                ]
            }
        await self._call("sendMessage", payload)

    async def _answer_callback(self, callback_id: str, text: str) -> None:
        if callback_id:
            await self._call(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": text[:200]},
            )

    async def _call(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        token = self._settings.market_ops_telegram_bot_token
        url = f"https://api.telegram.org/bot{token}/{method}"
        return await asyncio.to_thread(self._sender, url, payload, 10.0)

    def _authorized(self, chat: object, user: object) -> bool:
        if not isinstance(chat, dict) or str(chat.get("type", "")) != "private":
            return False
        if str(chat.get("id", "")) != self._settings.market_ops_telegram_interactive_allowed_chat_id:
            return False
        allowed_user = self._settings.market_ops_telegram_interactive_allowed_user_id
        return not allowed_user or (
            isinstance(user, dict) and str(user.get("id", "")) == allowed_user
        )

    def _rate_allowed(self) -> bool:
        now = self._now()
        cutoff = now - timedelta(minutes=1)
        while self._action_times and self._action_times[0] < cutoff:
            self._action_times.popleft()
        maximum = max(1, self._settings.market_ops_telegram_interactive_max_actions_per_minute)
        if len(self._action_times) >= maximum:
            return False
        self._action_times.append(now)
        return True

    def _configured(self) -> bool:
        return bool(
            self._settings.market_ops_telegram_interactive_enabled
            and self._settings.market_ops_notify_provider.strip().lower() == "telegram"
            and self._settings.market_ops_telegram_bot_token
            and self._settings.market_ops_telegram_interactive_allowed_chat_id
        )

    def _now(self) -> datetime:
        now = self._now_provider()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _telegram_request(
    url: str,
    payload: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(65536)
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("telegram_request_failed") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("telegram_invalid_response") from exc
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise RuntimeError("telegram_request_rejected")
    return parsed


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0
