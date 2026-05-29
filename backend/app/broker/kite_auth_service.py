"""Kite authentication and daily session lifecycle service."""

from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from typing import Protocol

from redis.asyncio import Redis

from app.broker.exceptions import (
    KiteAuthDisabledError,
    KiteConfigError,
    KiteSessionError,
    KiteStateError,
)
from app.broker.kite_client import KiteAuthClient
from app.broker.session_store import (
    BROKER_ZERODHA,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    BrokerSessionRecord,
    BrokerSessionStatus,
    SessionStore,
)
from app.broker.token_cipher import TokenCipher
from app.core.config import Settings

STATE_TTL_SECONDS = 300
STATE_PREFIX = "kite:auth:state:"
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class StateStore(Protocol):
    """Temporary callback-state storage."""

    async def create_state(self) -> str:
        """Create and store a temporary state token."""

    async def consume_state(self, state: str) -> bool:
        """Consume a state token exactly once."""


class RedisStateStore:
    """Redis-backed callback state store."""

    def __init__(self, redis_client: Redis, ttl_seconds: int = STATE_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def create_state(self) -> str:
        state = secrets.token_urlsafe(32)
        await self._redis.set(f"{STATE_PREFIX}{state}", "1", ex=self._ttl_seconds)
        return state

    async def consume_state(self, state: str) -> bool:
        if not state:
            return False
        key = f"{STATE_PREFIX}{state}"
        deleted = await self._redis.delete(key)
        return bool(deleted)


class KiteAuthService:
    """Coordinates the Kite login, callback, persistence, status and logout flow."""

    def __init__(
        self,
        *,
        settings: Settings,
        kite_client: KiteAuthClient,
        session_store: SessionStore,
        state_store: StateStore,
        token_cipher: TokenCipher | None = None,
    ) -> None:
        self._settings = settings
        self._kite_client = kite_client
        self._session_store = session_store
        self._state_store = state_store
        self._token_cipher = token_cipher

    async def create_login_url(self) -> dict[str, str]:
        """Create a Kite login URL with a temporary state token."""
        self._ensure_enabled_and_configured(require_cipher=False)
        state = await self._state_store.create_state()
        return {"login_url": self._kite_client.login_url(state)}

    async def handle_callback(self, *, request_token: str | None, state: str | None) -> dict[str, object]:
        """Validate state, exchange request token and persist encrypted access token."""
        self._ensure_enabled_and_configured(require_cipher=True)
        if not request_token:
            raise KiteStateError("Missing Kite request token.")
        if not state or not await self._state_store.consume_state(state):
            raise KiteStateError("Kite callback state is missing, invalid, or expired.")
        session_data = self._kite_client.exchange_request_token(request_token)
        if not session_data.access_token:
            raise KiteSessionError("Kite session exchange did not return an access token.")
        if self._token_cipher is None:
            raise KiteConfigError("Kite token cipher is not configured.")

        now_ist = datetime.now(IST)
        expires_at = next_kite_expiry(now_ist)
        encrypted_access_token = self._token_cipher.encrypt(session_data.access_token)
        record = await self._session_store.save_authenticated_session(
            broker=BROKER_ZERODHA,
            user_id=session_data.user_id or None,
            encrypted_access_token=encrypted_access_token,
            login_at=now_ist,
            expires_at=expires_at,
        )
        status = self._status_from_record(record)
        return asdict(status)

    async def get_status(self) -> dict[str, object]:
        """Return only non-sensitive session status."""
        if not self._settings.kite_auth_enabled:
            return asdict(
                BrokerSessionStatus(
                    configured=self._has_required_config(require_cipher=False),
                    enabled=False,
                    authenticated=False,
                    broker=BROKER_ZERODHA,
                    user_id=None,
                    login_at=None,
                    expires_at=None,
                    expired=False,
                    status=None,
                )
            )
        record = await self._session_store.get_latest_session(BROKER_ZERODHA)
        if record is None:
            return asdict(
                BrokerSessionStatus(
                    configured=self._has_required_config(require_cipher=True),
                    enabled=True,
                    authenticated=False,
                    broker=BROKER_ZERODHA,
                    user_id=None,
                    login_at=None,
                    expires_at=None,
                    expired=False,
                    status=None,
                )
            )
        status = self._status_from_record(record)
        if status.expired and record.status == STATUS_ACTIVE:
            await self._session_store.mark_invalidated(record.id, STATUS_EXPIRED)
        return asdict(status)

    async def logout(self) -> dict[str, object]:
        """Invalidate the current Kite session without exposing token material."""
        self._ensure_enabled_and_configured(require_cipher=True)
        record = await self._session_store.get_latest_session(BROKER_ZERODHA)
        if record is None:
            return {"logged_out": False, "reason": "no_session"}
        if self._token_cipher is None:
            raise KiteConfigError("Kite token cipher is not configured.")
        if record.status == STATUS_ACTIVE and not _is_expired(record.expires_at):
            access_token = self._token_cipher.decrypt(record.encrypted_access_token)
            self._kite_client.invalidate_access_token(access_token)
        await self._session_store.mark_invalidated(record.id)
        return {"logged_out": True}

    def _ensure_enabled_and_configured(self, *, require_cipher: bool) -> None:
        if not self._settings.kite_auth_enabled:
            raise KiteAuthDisabledError("Kite authentication is disabled.")
        if not self._has_required_config(require_cipher=require_cipher):
            raise KiteConfigError("Kite authentication configuration is incomplete.")

    def _has_required_config(self, *, require_cipher: bool) -> bool:
        required = [
            self._settings.kite_api_key,
            self._settings.kite_api_secret,
            self._settings.kite_redirect_url,
        ]
        if require_cipher:
            required.append(self._settings.kite_session_encryption_key)
        return all(bool(item) for item in required)

    def _status_from_record(self, record: BrokerSessionRecord) -> BrokerSessionStatus:
        expired = _is_expired(record.expires_at)
        authenticated = record.status == STATUS_ACTIVE and not expired and record.invalidated_at is None
        return BrokerSessionStatus(
            configured=self._has_required_config(require_cipher=True),
            enabled=self._settings.kite_auth_enabled,
            authenticated=authenticated,
            broker=record.broker,
            user_id=record.user_id,
            login_at=record.login_at,
            expires_at=record.expires_at,
            expired=expired,
            status=record.status,
        )


def next_kite_expiry(now: datetime) -> datetime:
    """Return the next 6:00 AM Asia/Kolkata token expiry boundary."""
    now_ist = now.astimezone(IST) if now.tzinfo else now.replace(tzinfo=IST)
    expiry = datetime.combine(now_ist.date(), time(hour=6), tzinfo=IST)
    if now_ist >= expiry:
        expiry += timedelta(days=1)
    return expiry


def _is_expired(expires_at: datetime) -> bool:
    now = datetime.now(expires_at.tzinfo or IST)
    return now >= expires_at
