"""Narrow Kite Connect authentication wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl


@dataclass(frozen=True)
class KiteSessionData:
    """Non-sensitive Kite session exchange result used by the auth service."""

    user_id: str
    access_token: str
    login_time: str | None = None


class KiteAuthClient(Protocol):
    """Auth-only Kite client interface for production and tests."""

    def login_url(self, state: str) -> str:
        """Build a Kite login URL with callback state."""

    def exchange_request_token(self, request_token: str) -> KiteSessionData:
        """Exchange a short-lived request token for session data."""

    def profile(self, access_token: str) -> dict[str, object]:
        """Retrieve profile for validating an authenticated session."""

    def invalidate_access_token(self, access_token: str) -> None:
        """Invalidate a Kite access token."""


class KiteConnectAuthClient:
    """Official KiteConnect-backed auth wrapper with no order or market-data methods."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret

    def _client(self) -> Any:
        from kiteconnect import KiteConnect  # type: ignore[import-untyped]

        return KiteConnect(api_key=self._api_key)

    def login_url(self, state: str) -> str:
        """Build a login URL and include state via Kite redirect_params."""
        client = self._client()
        base_url = client.login_url()
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query))
        query["redirect_params"] = urlencode({"state": state})
        return urlunparse(parsed._replace(query=urlencode(query)))

    def exchange_request_token(self, request_token: str) -> KiteSessionData:
        """Exchange request_token using the official client checksum flow."""
        client = self._client()
        data = client.generate_session(request_token, api_secret=self._api_secret)
        return KiteSessionData(
            user_id=str(data.get("user_id", "")),
            access_token=str(data["access_token"]),
            login_time=data.get("login_time"),
        )

    def profile(self, access_token: str) -> dict[str, object]:
        """Validate a session by retrieving the profile."""
        client = self._client()
        client.set_access_token(access_token)
        return dict(client.profile())

    def invalidate_access_token(self, access_token: str) -> None:
        """Invalidate only the active Kite API session token."""
        client = self._client()
        client.invalidate_access_token(access_token)
