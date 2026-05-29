"""Persistence for encrypted Kite broker sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import desc, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import broker_sessions

BROKER_ZERODHA = "ZERODHA"
STATUS_ACTIVE = "ACTIVE"
STATUS_LOGGED_OUT = "LOGGED_OUT"
STATUS_EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class BrokerSessionRecord:
    """Safe broker session record."""

    id: int
    broker: str
    user_id: str | None
    status: str
    login_at: datetime | None
    expires_at: datetime
    encrypted_access_token: str
    invalidated_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BrokerSessionStatus:
    """Non-sensitive broker session status returned by API routes."""

    configured: bool
    enabled: bool
    authenticated: bool
    broker: str
    user_id: str | None
    login_at: datetime | None
    expires_at: datetime | None
    expired: bool
    status: str | None


class SessionStore(Protocol):
    """Persistence interface for tests and production storage."""

    async def save_authenticated_session(
        self,
        *,
        broker: str,
        user_id: str | None,
        encrypted_access_token: str,
        login_at: datetime,
        expires_at: datetime,
    ) -> BrokerSessionRecord:
        """Persist an authenticated broker session."""

    async def get_latest_session(self, broker: str = BROKER_ZERODHA) -> BrokerSessionRecord | None:
        """Return the latest session for a broker."""

    async def mark_invalidated(self, session_id: int, status: str = STATUS_LOGGED_OUT) -> None:
        """Mark a broker session invalid or logged out."""


class SQLAlchemySessionStore:
    """SQLAlchemy-backed session store."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_authenticated_session(
        self,
        *,
        broker: str,
        user_id: str | None,
        encrypted_access_token: str,
        login_at: datetime,
        expires_at: datetime,
    ) -> BrokerSessionRecord:
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(broker_sessions)
            .where(
                broker_sessions.c.broker == broker,
                broker_sessions.c.status == STATUS_ACTIVE,
            )
            .values(status=STATUS_EXPIRED, updated_at=now)
        )
        result = await self._session.execute(
            insert(broker_sessions)
            .values(
                broker=broker,
                user_id=user_id,
                status=STATUS_ACTIVE,
                login_at=login_at,
                expires_at=expires_at,
                encrypted_access_token=encrypted_access_token,
                created_at=now,
                updated_at=now,
            )
            .returning(broker_sessions)
        )
        await self._session.commit()
        row = result.mappings().one()
        return _record_from_mapping(row)

    async def get_latest_session(self, broker: str = BROKER_ZERODHA) -> BrokerSessionRecord | None:
        result = await self._session.execute(
            select(broker_sessions)
            .where(broker_sessions.c.broker == broker)
            .order_by(desc(broker_sessions.c.created_at), desc(broker_sessions.c.id))
            .limit(1)
        )
        row = result.mappings().first()
        return _record_from_mapping(row) if row else None

    async def mark_invalidated(self, session_id: int, status: str = STATUS_LOGGED_OUT) -> None:
        await self._session.execute(
            update(broker_sessions)
            .where(broker_sessions.c.id == session_id)
            .values(
                status=status,
                invalidated_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()


def _record_from_mapping(row: Any) -> BrokerSessionRecord:
    return BrokerSessionRecord(
        id=int(row["id"]),
        broker=str(row["broker"]),
        user_id=row["user_id"],
        status=str(row["status"]),
        login_at=row["login_at"],
        expires_at=row["expires_at"],
        encrypted_access_token=str(row["encrypted_access_token"]),
        invalidated_at=row["invalidated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
