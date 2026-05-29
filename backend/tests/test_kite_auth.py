from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import get_kite_auth_service
from app.broker.exceptions import KiteAuthDisabledError, KiteConfigError, KiteStateError
from app.broker.kite_auth_service import KiteAuthService, next_kite_expiry
from app.broker.kite_client import KiteConnectAuthClient, KiteSessionData
from app.broker.session_store import (
    BROKER_ZERODHA,
    STATUS_ACTIVE,
    STATUS_LOGGED_OUT,
    BrokerSessionRecord,
)
from app.broker.token_cipher import TokenCipher
from app.core.config import Settings
from app.main import app

IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class FakeKiteClient:
    def __init__(self) -> None:
        self.invalidated: list[str] = []
        self.exchanged_tokens: list[str] = []

    def login_url(self, state: str) -> str:
        return f"https://kite.example/login?redirect_params=state%3D{state}"

    def exchange_request_token(self, request_token: str) -> KiteSessionData:
        self.exchanged_tokens.append(request_token)
        return KiteSessionData(user_id="AB1234", access_token="plain-access-token")

    def profile(self, access_token: str) -> dict[str, object]:
        return {"user_id": "AB1234"}

    def invalidate_access_token(self, access_token: str) -> None:
        self.invalidated.append(access_token)


class FakeStateStore:
    def __init__(self) -> None:
        self.states: set[str] = set()
        self.next_state = "state-123"

    async def create_state(self) -> str:
        self.states.add(self.next_state)
        return self.next_state

    async def consume_state(self, state: str) -> bool:
        if state in self.states:
            self.states.remove(state)
            return True
        return False


class FakeSessionStore:
    def __init__(self) -> None:
        self.latest: BrokerSessionRecord | None = None
        self.saved_encrypted_token: str | None = None
        self.invalidated: list[tuple[int, str]] = []

    async def save_authenticated_session(
        self,
        *,
        broker: str,
        user_id: str | None,
        encrypted_access_token: str,
        login_at: datetime,
        expires_at: datetime,
    ) -> BrokerSessionRecord:
        self.saved_encrypted_token = encrypted_access_token
        self.latest = BrokerSessionRecord(
            id=1,
            broker=broker,
            user_id=user_id,
            status=STATUS_ACTIVE,
            login_at=login_at,
            expires_at=expires_at,
            encrypted_access_token=encrypted_access_token,
            invalidated_at=None,
            created_at=login_at,
            updated_at=login_at,
        )
        return self.latest

    async def get_latest_session(self, broker: str = BROKER_ZERODHA) -> BrokerSessionRecord | None:
        return self.latest if self.latest and self.latest.broker == broker else None

    async def mark_invalidated(self, session_id: int, status: str = STATUS_LOGGED_OUT) -> None:
        self.invalidated.append((session_id, status))
        if self.latest:
            self.latest = replace(self.latest, status=status)


def enabled_settings() -> Settings:
    return Settings(
        kite_auth_enabled=True,
        kite_api_key="fake-key",
        kite_api_secret="fake-secret",
        kite_redirect_url="https://example.test/api/v1/broker/kite/callback",
        kite_session_encryption_key=TokenCipher.generate_key(),
        operator_auth_token="operator-secret",
    )


def make_service(settings: Settings | None = None) -> tuple[KiteAuthService, FakeKiteClient, FakeSessionStore, FakeStateStore]:
    actual_settings = settings or enabled_settings()
    client = FakeKiteClient()
    session_store = FakeSessionStore()
    state_store = FakeStateStore()
    cipher = (
        TokenCipher(actual_settings.kite_session_encryption_key)
        if actual_settings.kite_session_encryption_key
        else None
    )
    service = KiteAuthService(
        settings=actual_settings,
        kite_client=client,
        session_store=session_store,
        state_store=state_store,
        token_cipher=cipher,
    )
    return service, client, session_store, state_store


@pytest.mark.asyncio
async def test_kite_auth_disabled_refuses_login_initiation() -> None:
    service, _, _, _ = make_service(Settings(kite_auth_enabled=False))

    with pytest.raises(KiteAuthDisabledError):
        await service.create_login_url()


@pytest.mark.asyncio
async def test_missing_kite_configuration_fails_safely() -> None:
    service, _, _, _ = make_service(Settings(kite_auth_enabled=True))

    with pytest.raises(KiteConfigError):
        await service.create_login_url()


@pytest.mark.asyncio
async def test_login_url_creation_succeeds_with_fake_kite_client() -> None:
    service, _, _, state_store = make_service()

    response = await service.create_login_url()

    assert "state-123" in response["login_url"]
    assert "state-123" in state_store.states


@pytest.mark.asyncio
async def test_callback_rejects_missing_or_incorrect_state() -> None:
    service, _, _, _ = make_service()

    with pytest.raises(KiteStateError):
        await service.handle_callback(request_token="request-token", state="bad-state")


@pytest.mark.asyncio
async def test_valid_callback_persists_only_encrypted_token_data() -> None:
    service, client, session_store, state_store = make_service()
    await state_store.create_state()

    response = await service.handle_callback(request_token="request-token", state="state-123")

    assert client.exchanged_tokens == ["request-token"]
    assert session_store.saved_encrypted_token is not None
    assert session_store.saved_encrypted_token != "plain-access-token"
    assert "access_token" not in response
    assert "encrypted_access_token" not in response
    assert response["authenticated"] is True
    assert response["user_id"] == "AB1234"


def test_token_cipher_encrypts_and_decrypts_only_through_cipher() -> None:
    cipher = TokenCipher(TokenCipher.generate_key())

    encrypted = cipher.encrypt("plain-access-token")

    assert encrypted != "plain-access-token"
    assert cipher.decrypt(encrypted) == "plain-access-token"


@pytest.mark.asyncio
async def test_session_status_never_returns_token_data() -> None:
    service, _, _, state_store = make_service()
    await state_store.create_state()
    await service.handle_callback(request_token="request-token", state="state-123")

    response = await service.get_status()

    assert "access_token" not in response
    assert "encrypted_access_token" not in response
    assert response["authenticated"] is True


def test_expiry_is_next_6am_asia_kolkata() -> None:
    assert next_kite_expiry(datetime(2026, 5, 29, 5, 0, tzinfo=IST)) == datetime(
        2026, 5, 29, 6, 0, tzinfo=IST
    )
    assert next_kite_expiry(datetime(2026, 5, 29, 9, 30, tzinfo=IST)) == datetime(
        2026, 5, 30, 6, 0, tzinfo=IST
    )


@pytest.mark.asyncio
async def test_logout_invalidates_fake_session_and_marks_inactive() -> None:
    service, client, session_store, state_store = make_service()
    await state_store.create_state()
    await service.handle_callback(request_token="request-token", state="state-123")

    response = await service.logout()

    assert response == {"logged_out": True}
    assert client.invalidated == ["plain-access-token"]
    assert session_store.invalidated == [(1, STATUS_LOGGED_OUT)]


def test_operator_protected_routes_reject_absent_or_invalid_token(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")
    client = TestClient(app)

    missing = client.post("/api/v1/broker/kite/login-url")
    invalid = client.post("/api/v1/broker/kite/login-url", headers={"X-Operator-Token": "bad"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_login_route_uses_operator_token_and_fake_service(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def create_login_url(self) -> dict[str, str]:
            return {"login_url": "https://kite.example/login"}

    app.dependency_overrides[get_kite_auth_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/broker/kite/login-url",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"login_url": "https://kite.example/login"}


def test_kite_connect_wrapper_exposes_no_order_or_market_data_methods() -> None:
    forbidden_fragments = ("order", "position", "holding", "quote", "historical", "ticker", "websocket")
    public_methods = {
        name
        for name in dir(KiteConnectAuthClient)
        if not name.startswith("_") and callable(getattr(KiteConnectAuthClient, name))
    }

    assert public_methods == {
        "login_url",
        "exchange_request_token",
        "profile",
        "invalidate_access_token",
    }
    assert not any(fragment in method for fragment in forbidden_fragments for method in public_methods)
