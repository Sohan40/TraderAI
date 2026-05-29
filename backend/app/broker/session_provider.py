"""Internal access to decrypted Kite sessions for read-only backend services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.broker.exceptions import KiteAuthDisabledError, KiteConfigError, KiteSessionError
from app.broker.session_store import BROKER_ZERODHA, STATUS_ACTIVE, SessionStore
from app.broker.token_cipher import TokenCipher
from app.core.config import Settings


@dataclass(frozen=True)
class KiteAccessSession:
    """Internal-only decrypted Kite access session."""

    api_key: str
    access_token: str
    user_id: str | None
    expires_at: datetime


class AccessSessionProvider(Protocol):
    """Protocol for internal services that need a decrypted active session."""

    async def get_active_session(self) -> KiteAccessSession:
        """Return a decrypted active Kite session."""


class KiteAccessSessionProvider:
    """Load and decrypt the active Kite session without exposing it to routes."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_store: SessionStore,
        token_cipher: TokenCipher | None,
    ) -> None:
        self._settings = settings
        self._session_store = session_store
        self._token_cipher = token_cipher

    async def get_active_session(self) -> KiteAccessSession:
        """Return a decrypted active session or fail safely."""
        if not self._settings.kite_auth_enabled:
            raise KiteAuthDisabledError("Kite auth is disabled.")
        if not self._settings.kite_api_key:
            raise KiteConfigError("Kite API key is not configured.")
        if self._token_cipher is None:
            raise KiteConfigError("Kite session encryption is not configured.")

        record = await self._session_store.get_latest_session(BROKER_ZERODHA)
        if record is None:
            raise KiteSessionError("No Kite session is available.")
        if record.status != STATUS_ACTIVE or record.invalidated_at is not None:
            raise KiteSessionError("Kite session is not active.")
        now = datetime.now(timezone.utc)
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise KiteSessionError("Kite session is expired.")

        return KiteAccessSession(
            api_key=self._settings.kite_api_key,
            access_token=self._token_cipher.decrypt(record.encrypted_access_token),
            user_id=record.user_id,
            expires_at=expires_at,
        )
