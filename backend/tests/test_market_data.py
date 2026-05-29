from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import get_market_data_stream_service
from app.broker.exceptions import KiteSessionError
from app.broker.session_provider import KiteAccessSession, KiteAccessSessionProvider
from app.broker.session_store import BROKER_ZERODHA, STATUS_ACTIVE, BrokerSessionRecord
from app.broker.token_cipher import TokenCipher
from app.core.config import Settings
from app.main import app
from app.market_data.candle_builder import OneMinuteCandleBuilder
from app.market_data.exceptions import (
    InstrumentSyncDisabledError,
    MarketDataDisabledError,
    MarketDataSessionError,
    WatchlistError,
)
from app.market_data.instrument_sync import InstrumentSyncService
from app.market_data.kite_market_client import KiteConnectMarketClient, KiteQuoteStream
from app.market_data.schemas import CompletedCandle, InstrumentRecord, NormalizedTick
from app.market_data.watchlist import parse_watchlist
from app.market_data.websocket_service import MarketDataStreamService


class FakeMarketClient:
    def __init__(self) -> None:
        self.stream = FakeStream()
        self.subscribed: list[int] = []
        self.modes: list[tuple[str, list[int]]] = []
        self.fetched_with: tuple[str, str] | None = None

    def fetch_instruments(self, *, api_key: str, access_token: str) -> list[Mapping[str, Any]]:
        self.fetched_with = (api_key, access_token)
        return [
            {
                "instrument_token": 111,
                "exchange": "NSE",
                "tradingsymbol": "NIFTYBEES",
                "name": "Nippon India ETF Nifty BeES",
                "instrument_type": "EQ",
                "tick_size": "0.01",
                "lot_size": 1,
            },
            {
                "instrument_token": 222,
                "exchange": "NSE",
                "tradingsymbol": "IGNORED",
                "name": "Ignored",
                "instrument_type": "EQ",
                "tick_size": "0.01",
                "lot_size": 1,
            },
        ]

    def create_quote_stream(
        self,
        *,
        api_key: str,
        access_token: str,
        on_ticks: Callable[[list[Mapping[str, Any]]], None],
        on_connect: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> "FakeStream":
        self.stream.kwargs = {
            "api_key": api_key,
            "access_token": access_token,
            "on_ticks": on_ticks,
            "on_connect": on_connect,
            "on_close": on_close,
            "on_error": on_error,
        }
        return self.stream

    def subscribe(self, stream: KiteQuoteStream, instrument_tokens: Sequence[int]) -> None:
        self.subscribed = list(instrument_tokens)
        stream.subscribe(instrument_tokens)

    def set_mode(self, stream: KiteQuoteStream, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.modes.append((mode, list(instrument_tokens)))
        stream.set_mode(mode, instrument_tokens)

    def disconnect(self, stream: KiteQuoteStream) -> None:
        stream.close()


class FakeStream:
    def __init__(self) -> None:
        self.on_ticks: Any = None
        self.on_connect: Any = None
        self.on_close: Any = None
        self.on_error: Any = None
        self.kwargs: dict[str, Any] = {}
        self.connected = False
        self.closed = False
        self.tokens: list[int] = []
        self.mode: str | None = None

    def connect(self, threaded: bool = True) -> None:
        self.connected = True

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.tokens = list(instrument_tokens)

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.mode = mode
        self.tokens = list(instrument_tokens)

    def close(self) -> None:
        self.closed = True
        self.connected = False


class FakeSessionProvider:
    def __init__(self, *, expired: bool = False, fail: bool = False) -> None:
        self.expired = expired
        self.fail = fail

    async def get_active_session(self) -> KiteAccessSession:
        if self.fail:
            raise KiteSessionError("missing session")
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        if not self.expired:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        if expires_at <= datetime.now(timezone.utc):
            raise KiteSessionError("expired session")
        return KiteAccessSession(
            api_key="fake-api-key",
            access_token="decrypted-token",
            user_id="AB1234",
            expires_at=expires_at,
        )


class FakeRepository:
    def __init__(self) -> None:
        self.instruments: dict[str, InstrumentRecord] = {}
        self.saved_candles: list[CompletedCandle] = []

    async def upsert_instruments(self, broker_instruments, watchlist):
        wanted = {symbol.key for symbol in watchlist}
        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        for item in broker_instruments:
            key = f"{item['exchange']}:{item['tradingsymbol']}"
            if key not in wanted:
                skipped += 1
                continue
            record = InstrumentRecord(
                id=len(self.instruments) + 1,
                exchange=str(item["exchange"]),
                tradingsymbol=str(item["tradingsymbol"]),
                instrument_token=int(item["instrument_token"]),
                tick_size=Decimal(str(item["tick_size"])),
            )
            if key in self.instruments:
                updated += 1
                record = replace(record, id=self.instruments[key].id)
            else:
                inserted += 1
            self.instruments[key] = record
        from app.market_data.schemas import InstrumentSyncResult

        return InstrumentSyncResult(
            fetched=len(broker_instruments),
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            failed=failed,
        )

    async def resolve_watchlist(self, watchlist):
        return [self.instruments[symbol.key] for symbol in watchlist if symbol.key in self.instruments]

    async def save_completed_candles(self, completed):
        self.saved_candles.extend(completed)
        return len(completed)


class FakeBrokerSessionStore:
    def __init__(self, record: BrokerSessionRecord | None) -> None:
        self.record = record

    async def save_authenticated_session(self, **kwargs):
        raise AssertionError("not used")

    async def get_latest_session(self, broker: str = BROKER_ZERODHA):
        return self.record if self.record and broker == BROKER_ZERODHA else None

    async def mark_invalidated(self, session_id: int, status: str = "LOGGED_OUT") -> None:
        raise AssertionError("not used")


def market_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "kite_auth_enabled": True,
        "kite_api_key": "fake-api-key",
        "kite_session_encryption_key": TokenCipher.generate_key(),
        "operator_auth_token": "operator-secret",
        "market_data_enabled": True,
        "instrument_sync_enabled": True,
        "kite_websocket_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_market_data_flags_are_disabled_by_default() -> None:
    settings = Settings()

    assert settings.market_data_enabled is False
    assert settings.instrument_sync_enabled is False
    assert settings.kite_websocket_enabled is False
    assert settings.market_data_mode == "quote"


@pytest.mark.asyncio
async def test_instrument_sync_refuses_when_disabled() -> None:
    service = InstrumentSyncService(
        settings=market_settings(instrument_sync_enabled=False),
        market_client=FakeMarketClient(),
        repository=FakeRepository(),
        session_provider=FakeSessionProvider(),
    )

    with pytest.raises(InstrumentSyncDisabledError):
        await service.sync()


@pytest.mark.asyncio
async def test_stream_start_refuses_when_market_data_disabled() -> None:
    service = MarketDataStreamService(
        settings=market_settings(market_data_enabled=False),
        market_client=FakeMarketClient(),
        repository=FakeRepository(),
        session_provider=FakeSessionProvider(),
    )

    with pytest.raises(MarketDataDisabledError):
        await service.start()


@pytest.mark.asyncio
async def test_stream_start_refuses_when_kite_websocket_disabled() -> None:
    service = MarketDataStreamService(
        settings=market_settings(kite_websocket_enabled=False),
        market_client=FakeMarketClient(),
        repository=FakeRepository(),
        session_provider=FakeSessionProvider(),
    )

    with pytest.raises(MarketDataDisabledError):
        await service.start()


@pytest.mark.asyncio
async def test_stream_start_refuses_without_valid_authenticated_session() -> None:
    repository = FakeRepository()
    repository.instruments["NSE:NIFTYBEES"] = InstrumentRecord(1, "NSE", "NIFTYBEES", 111, Decimal("0.01"))
    repository.instruments["NSE:SBIN"] = InstrumentRecord(2, "NSE", "SBIN", 222, Decimal("0.05"))
    service = MarketDataStreamService(
        settings=market_settings(),
        market_client=FakeMarketClient(),
        repository=repository,
        session_provider=FakeSessionProvider(fail=True),
    )

    with pytest.raises(MarketDataSessionError):
        await service.start()


@pytest.mark.asyncio
async def test_stream_start_refuses_when_session_is_expired() -> None:
    repository = FakeRepository()
    repository.instruments["NSE:NIFTYBEES"] = InstrumentRecord(1, "NSE", "NIFTYBEES", 111, Decimal("0.01"))
    repository.instruments["NSE:SBIN"] = InstrumentRecord(2, "NSE", "SBIN", 222, Decimal("0.05"))
    service = MarketDataStreamService(
        settings=market_settings(),
        market_client=FakeMarketClient(),
        repository=repository,
        session_provider=FakeSessionProvider(expired=True),
    )

    with pytest.raises(MarketDataSessionError):
        await service.start()


@pytest.mark.asyncio
async def test_stream_start_refuses_unresolved_watchlist_symbols() -> None:
    repository = FakeRepository()
    repository.instruments["NSE:NIFTYBEES"] = InstrumentRecord(1, "NSE", "NIFTYBEES", 111, Decimal("0.01"))
    service = MarketDataStreamService(
        settings=market_settings(),
        market_client=FakeMarketClient(),
        repository=repository,
        session_provider=FakeSessionProvider(),
    )

    with pytest.raises(WatchlistError):
        await service.start()


def test_watchlist_parsing_nse_restriction_and_maximum() -> None:
    symbols = parse_watchlist("NSE:NIFTYBEES,NSE:SBIN", 2)

    assert [symbol.key for symbol in symbols] == ["NSE:NIFTYBEES", "NSE:SBIN"]
    with pytest.raises(WatchlistError):
        parse_watchlist("BSE:SBIN", 2)
    with pytest.raises(WatchlistError):
        parse_watchlist("NSE:SBIN,NSE:SBIN", 2)
    with pytest.raises(WatchlistError):
        parse_watchlist("NSE:A,NSE:B,NSE:C", 2)


@pytest.mark.asyncio
async def test_instrument_upsert_for_fake_response() -> None:
    repository = FakeRepository()
    client = FakeMarketClient()
    service = InstrumentSyncService(
        settings=market_settings(market_data_watchlist="NSE:NIFTYBEES"),
        market_client=client,
        repository=repository,
        session_provider=FakeSessionProvider(),
    )

    result = await service.sync()

    assert client.fetched_with == ("fake-api-key", "decrypted-token")
    assert result.inserted == 1
    assert result.skipped == 1
    assert repository.instruments["NSE:NIFTYBEES"].instrument_token == 111


@pytest.mark.asyncio
async def test_websocket_subscription_uses_resolved_instruments_and_quote_mode() -> None:
    repository = FakeRepository()
    repository.instruments["NSE:NIFTYBEES"] = InstrumentRecord(1, "NSE", "NIFTYBEES", 111, Decimal("0.01"))
    repository.instruments["NSE:SBIN"] = InstrumentRecord(2, "NSE", "SBIN", 222, Decimal("0.05"))
    client = FakeMarketClient()
    service = MarketDataStreamService(
        settings=market_settings(),
        market_client=client,
        repository=repository,
        session_provider=FakeSessionProvider(),
    )

    status = await service.start()

    assert client.subscribed == [111, 222]
    assert client.modes == [("quote", [111, 222])]
    assert status["connected"] is True
    assert status["subscribed_symbols"] == 2


@pytest.mark.asyncio
async def test_normalized_ticks_create_completed_one_minute_candles() -> None:
    repository = FakeRepository()
    repository.instruments["NSE:NIFTYBEES"] = InstrumentRecord(1, "NSE", "NIFTYBEES", 111, Decimal("0.01"))
    client = FakeMarketClient()
    service = MarketDataStreamService(
        settings=market_settings(market_data_watchlist="NSE:NIFTYBEES"),
        market_client=client,
        repository=repository,
        session_provider=FakeSessionProvider(),
        candle_builder=OneMinuteCandleBuilder(),
    )
    await service.start()

    service.handle_ticks(
        [
            {"instrument_token": 111, "last_price": "9.75", "volume": 80, "exchange_timestamp": datetime(2026, 5, 30, 9, 14, 59, tzinfo=timezone.utc)},
            {"instrument_token": 111, "last_price": "10.00", "volume": 100, "exchange_timestamp": datetime(2026, 5, 30, 9, 15, 1, tzinfo=timezone.utc)},
            {"instrument_token": 111, "last_price": "11.00", "volume": 120, "exchange_timestamp": datetime(2026, 5, 30, 9, 15, 20, tzinfo=timezone.utc)},
            {"instrument_token": 111, "last_price": "9.50", "volume": 90, "exchange_timestamp": datetime(2026, 5, 30, 9, 15, 10, tzinfo=timezone.utc)},
            {"instrument_token": 111, "last_price": "12.00", "volume": 130, "exchange_timestamp": datetime(2026, 5, 30, 9, 16, 1, tzinfo=timezone.utc)},
        ]
    )
    await asyncio.sleep(0)

    assert len(repository.saved_candles) == 1
    candle = repository.saved_candles[0]
    assert candle.open_price == Decimal("10.00")
    assert candle.high_price == Decimal("11.00")
    assert candle.low_price == Decimal("10.00")
    assert candle.close_price == Decimal("11.00")
    assert candle.volume == 40
    assert candle.source == "KITE_WEBSOCKET"


def test_cross_minute_cumulative_volume_uses_previous_tick_baseline() -> None:
    builder = OneMinuteCandleBuilder()

    assert builder.accept_tick(_tick("09:59:59", "99.00", 1000), instrument_id=1) == []
    assert builder.accept_tick(_tick("10:00:08", "100.00", 1040), instrument_id=1) == []
    assert builder.accept_tick(_tick("10:00:55", "101.00", 1090), instrument_id=1) == []
    completed = builder.accept_tick(_tick("10:01:01", "102.00", 1100), instrument_id=1)

    assert len(completed) == 1
    assert completed[0].started_at == datetime(2026, 5, 30, 10, 0, tzinfo=timezone.utc)
    assert completed[0].volume == 90


def test_stream_start_partial_candle_is_not_persisted() -> None:
    builder = OneMinuteCandleBuilder()

    assert builder.accept_tick(_tick("09:15:01", "10.00", 100), instrument_id=1) == []
    assert builder.accept_tick(_tick("09:15:20", "11.00", 120), instrument_id=1) == []
    assert builder.accept_tick(_tick("09:16:01", "12.00", 150), instrument_id=1) == []


def test_exact_duplicate_ticks_do_not_double_count_volume() -> None:
    builder = OneMinuteCandleBuilder()

    builder.accept_tick(_tick("09:59:59", "99.00", 1000), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.00", 1040), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.00", 1040), instrument_id=1)
    builder.accept_tick(_tick("10:00:55", "101.00", 1090), instrument_id=1)
    completed = builder.accept_tick(_tick("10:01:01", "102.00", 1100), instrument_id=1)

    assert completed[0].volume == 90


def test_same_timestamp_higher_cumulative_volume_counts_increment_once() -> None:
    builder = OneMinuteCandleBuilder()

    builder.accept_tick(_tick("09:59:59", "99.00", 1000), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.00", 1040), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.50", 1090), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.50", 1090), instrument_id=1)
    completed = builder.accept_tick(_tick("10:01:01", "102.00", 1100), instrument_id=1)

    assert completed[0].high_price == Decimal("100.50")
    assert completed[0].close_price == Decimal("100.50")
    assert completed[0].volume == 90


def test_cumulative_volume_decrease_discards_affected_candle() -> None:
    builder = OneMinuteCandleBuilder()

    builder.accept_tick(_tick("09:59:59", "99.00", 1000), instrument_id=1)
    builder.accept_tick(_tick("10:00:08", "100.00", 1040), instrument_id=1)
    builder.accept_tick(_tick("10:00:55", "101.00", 1030), instrument_id=1)
    completed = builder.accept_tick(_tick("10:01:01", "102.00", 1040), instrument_id=1)

    assert completed == []


def test_stream_status_returns_no_secret_values() -> None:
    service = MarketDataStreamService(
        settings=market_settings(),
        market_client=FakeMarketClient(),
        repository=FakeRepository(),
        session_provider=FakeSessionProvider(),
    )

    status = service.status_dict()
    rendered = str(status)

    assert "decrypted-token" not in rendered
    assert "fake-api-key" not in rendered
    assert "operator-secret" not in rendered
    assert "access_token" not in status


def test_market_data_routes_require_operator_token(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")
    client = TestClient(app)

    missing = client.get("/api/v1/market-data/status")
    invalid = client.get("/api/v1/market-data/status", headers={"X-Operator-Token": "bad"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_market_data_status_route_returns_safe_fake_status(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        def status_dict(self) -> dict[str, object]:
            return {"enabled": False, "running": False, "mode": "quote"}

    app.dependency_overrides[get_market_data_stream_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/market-data/status",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "running": False, "mode": "quote"}


@pytest.mark.asyncio
async def test_encrypted_p03_session_provider_decrypts_only_internally() -> None:
    key = TokenCipher.generate_key()
    cipher = TokenCipher(key)
    encrypted = cipher.encrypt("plain-access-token")
    record = BrokerSessionRecord(
        id=1,
        broker=BROKER_ZERODHA,
        user_id="AB1234",
        status=STATUS_ACTIVE,
        login_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        encrypted_access_token=encrypted,
        invalidated_at=None,
    )
    provider = KiteAccessSessionProvider(
        settings=market_settings(kite_session_encryption_key=key),
        session_store=FakeBrokerSessionStore(record),
        token_cipher=cipher,
    )

    session = await provider.get_active_session()

    assert encrypted != "plain-access-token"
    assert session.access_token == "plain-access-token"


@pytest.mark.asyncio
async def test_invalidated_p03_session_prevents_market_data_startup() -> None:
    key = TokenCipher.generate_key()
    cipher = TokenCipher(key)
    record = BrokerSessionRecord(
        id=1,
        broker=BROKER_ZERODHA,
        user_id="AB1234",
        status=STATUS_ACTIVE,
        login_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        encrypted_access_token=cipher.encrypt("plain-access-token"),
        invalidated_at=datetime.now(timezone.utc),
    )
    provider = KiteAccessSessionProvider(
        settings=market_settings(kite_session_encryption_key=key),
        session_store=FakeBrokerSessionStore(record),
        token_cipher=cipher,
    )

    with pytest.raises(KiteSessionError):
        await provider.get_active_session()


def test_market_data_wrapper_exposes_no_execution_methods() -> None:
    forbidden_fragments = ("order", "position", "holding", "margin", "gtt")
    public_methods = {
        name
        for name in dir(KiteConnectMarketClient)
        if not name.startswith("_") and callable(getattr(KiteConnectMarketClient, name))
    }

    assert public_methods == {
        "fetch_instruments",
        "create_quote_stream",
        "subscribe",
        "set_mode",
        "disconnect",
    }
    assert not any(fragment in method for fragment in forbidden_fragments for method in public_methods)


def _tick(time_text: str, price: str, volume: int) -> NormalizedTick:
    hour, minute, second = (int(part) for part in time_text.split(":"))
    return NormalizedTick(
        instrument_token=111,
        last_price=Decimal(price),
        volume=volume,
        exchange_timestamp=datetime(2026, 5, 30, hour, minute, second, tzinfo=timezone.utc),
    )
