from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import get_morning_readiness_service
from app.broker.session_store import BROKER_ZERODHA, STATUS_ACTIVE, BrokerSessionRecord
from app.core.config import Settings
from app.main import app
from app.market_data.schemas import (
    CompletedCandle,
    InstrumentRecord,
    InstrumentSyncResult,
    WatchlistSymbol,
)
from app.market_data.stream_readiness import StreamReadinessService
from app.market_data.watchlist_validation import WatchlistValidationService
from app.ops.morning_readiness import MorningReadinessService
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.repository import InMemoryScannerRepository
from app.scanners.service import ScannerService


class LocalMarketRepository:
    def __init__(self, records: Sequence[InstrumentRecord] = ()) -> None:
        self.records = {record.key: record for record in records}

    async def upsert_instruments(
        self,
        broker_instruments: Sequence[Mapping[str, object]],
        watchlist: Sequence[WatchlistSymbol],
    ) -> InstrumentSyncResult:
        raise AssertionError("not used")

    async def resolve_watchlist(
        self,
        watchlist: Sequence[WatchlistSymbol],
    ) -> list[InstrumentRecord]:
        return [
            self.records[symbol.key]
            for symbol in watchlist
            if symbol.key in self.records and self.records[symbol.key].is_active
        ]

    async def inspect_watchlist(
        self,
        watchlist: Sequence[WatchlistSymbol],
    ) -> list[InstrumentRecord]:
        return [self.records[symbol.key] for symbol in watchlist if symbol.key in self.records]

    async def save_completed_candles(self, completed: Sequence[CompletedCandle]) -> int:
        raise AssertionError("not used")


class LocalSessionStore:
    def __init__(self, record: BrokerSessionRecord | None) -> None:
        self.record = record

    async def save_authenticated_session(
        self,
        *,
        broker: str,
        user_id: str | None,
        encrypted_access_token: str,
        login_at: datetime,
        expires_at: datetime,
    ) -> BrokerSessionRecord:
        raise AssertionError("not used")

    async def get_latest_session(
        self,
        broker: str = BROKER_ZERODHA,
    ) -> BrokerSessionRecord | None:
        return self.record if broker == BROKER_ZERODHA else None

    async def mark_invalidated(self, session_id: int, status: str = "LOGGED_OUT") -> None:
        raise AssertionError("not used")


class LocalStreamStatus:
    def __init__(self, *, running: bool, connected: bool) -> None:
        self.running = running
        self.connected = connected

    def status_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "connected": self.connected,
            "subscribed_symbols": 1 if self.connected else 0,
            "last_error": None,
        }


async def test_morning_readiness_blocks_invalid_watchlist() -> None:
    service = _morning_service(
        settings=_settings(market_data_watchlist="SBIN"),
        repository=LocalMarketRepository(),
        session_record=_active_session(),
        stream=LocalStreamStatus(running=True, connected=True),
    )

    result = await service.readiness()

    assert result["ready_for_market_open"] is False
    blocking = cast(list[str], result["blocking_issues"])
    assert "watchlist_entries_must_use_exchange_colon_tradingsymbol" in blocking


async def test_morning_readiness_blocks_missing_kite_session() -> None:
    service = _morning_service(
        settings=_settings(),
        repository=LocalMarketRepository([_sbin()]),
        session_record=None,
        stream=LocalStreamStatus(running=True, connected=True),
    )

    result = await service.readiness()

    assert result["ready_for_market_open"] is False
    blocking = cast(list[str], result["blocking_issues"])
    sequence = cast(list[str], result["recommended_sequence"])
    assert "kite_session_not_ready" in blocking
    assert "login_kite" in sequence


async def test_morning_readiness_warns_when_paper_is_enabled() -> None:
    service = _morning_service(
        settings=_settings(paper_enabled=True, paper_mode="PAPER"),
        repository=LocalMarketRepository([_sbin()]),
        session_record=_active_session(),
        stream=LocalStreamStatus(running=True, connected=True),
    )

    result = await service.readiness()

    warnings = cast(list[str], result["warnings"])
    assert "paper_mode_should_remain_off_during_market_readiness" in warnings


async def test_morning_readiness_is_ready_when_all_local_gates_pass() -> None:
    service = _morning_service(
        settings=_settings(),
        repository=LocalMarketRepository([_sbin()]),
        session_record=_active_session(),
        stream=LocalStreamStatus(running=True, connected=True),
    )

    result = await service.readiness()

    assert result["safe"] is True
    assert result["ready_for_market_open"] is True
    assert result["blocking_issues"] == []


def test_morning_readiness_route_requires_operator_token_and_returns_safe_report(
    monkeypatch,
) -> None:
    monkeypatch.setattr(dependencies.settings, "operator_auth_token", "operator-secret")

    class RouteService:
        async def readiness(self) -> dict[str, object]:
            return {
                "safe": True,
                "ready_for_market_open": False,
                "blocking_issues": ["market_stream_not_running"],
                "warnings": [],
                "recommended_sequence": ["start_market_stream"],
            }

    app.dependency_overrides[get_morning_readiness_service] = lambda: RouteService()
    try:
        client = TestClient(app)
        missing = client.get("/api/v1/ops/morning-readiness")
        response = client.get(
            "/api/v1/ops/morning-readiness",
            headers={"X-Operator-Token": "operator-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert response.status_code == 200
    assert response.json()["recommended_sequence"] == ["start_market_stream"]
    assert "operator-secret" not in str(response.json())


def _morning_service(
    *,
    settings: Settings,
    repository: LocalMarketRepository,
    session_record: BrokerSessionRecord | None,
    stream: LocalStreamStatus,
) -> MorningReadinessService:
    watchlist = WatchlistValidationService(settings=settings, repository=repository)
    stream_readiness = StreamReadinessService(
        settings=settings,
        watchlist_service=watchlist,
        session_store=LocalSessionStore(session_record),
        stream_status_provider=stream,
    )
    scanner = ScannerService(
        settings=settings,
        repository=InMemoryScannerRepository(),
    )
    auto_loop = ScannerAutoLoopService(
        settings=settings,
        scanner_service=scanner,
    )
    return MorningReadinessService(
        settings=settings,
        watchlist_service=watchlist,
        stream_readiness_service=stream_readiness,
        scanner_service=scanner,
        auto_loop_service=auto_loop,
    )


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "trading_mode": "OFF",
        "live_armed": False,
        "paper_enabled": False,
        "paper_mode": "OFF",
        "kite_auth_enabled": True,
        "kite_api_key": "configured",
        "kite_session_encryption_key": "configured",
        "market_data_enabled": True,
        "kite_websocket_enabled": True,
        "market_data_watchlist": "NSE:SBIN",
        "market_data_max_instruments": 20,
        "scanner_enabled": True,
        "scanner_auto_loop_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def _sbin() -> InstrumentRecord:
    return InstrumentRecord(
        id=1,
        exchange="NSE",
        tradingsymbol="SBIN",
        instrument_token=111,
        tick_size=Decimal("0.05"),
    )


def _active_session() -> BrokerSessionRecord:
    return BrokerSessionRecord(
        id=1,
        broker=BROKER_ZERODHA,
        user_id="AB1234",
        status=STATUS_ACTIVE,
        login_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        encrypted_access_token="encrypted",
        invalidated_at=None,
    )
