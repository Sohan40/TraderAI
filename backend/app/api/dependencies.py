"""Shared FastAPI dependencies."""

from hmac import compare_digest

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.kite_auth_service import KiteAuthService, RedisStateStore
from app.broker.kite_client import KiteConnectAuthClient
from app.broker.session_provider import KiteAccessSessionProvider
from app.broker.session_store import SQLAlchemySessionStore, SessionFactorySessionStore
from app.broker.token_cipher import TokenCipher
from app.cache.redis import get_redis_client
from app.core.config import settings
from app.db.session import async_session_factory, get_session
from app.market_data.instrument_sync import InstrumentSyncService
from app.market_data.kite_market_client import KiteConnectMarketClient
from app.market_data.repository import (
    SQLAlchemyMarketDataRepository,
    SessionFactoryMarketDataRepository,
)
from app.market_data.websocket_service import MarketDataStreamService

_market_data_stream_service: MarketDataStreamService | None = None


def require_operator_token(x_operator_token: str | None = Header(default=None)) -> None:
    """Authenticate operator-only endpoints with a configured header token."""
    if not settings.operator_auth_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication is not configured",
        )
    if x_operator_token is None or not compare_digest(x_operator_token, settings.operator_auth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid operator token",
        )


async def get_kite_auth_service(
    session: AsyncSession = Depends(get_session),
) -> KiteAuthService:
    """Build the Kite auth service from configured production dependencies."""
    token_cipher = (
        TokenCipher(settings.kite_session_encryption_key)
        if settings.kite_session_encryption_key
        else None
    )
    return KiteAuthService(
        settings=settings,
        kite_client=KiteConnectAuthClient(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
        ),
        session_store=SQLAlchemySessionStore(session),
        state_store=RedisStateStore(get_redis_client()),
        token_cipher=token_cipher,
    )


def _build_token_cipher() -> TokenCipher | None:
    return (
        TokenCipher(settings.kite_session_encryption_key)
        if settings.kite_session_encryption_key
        else None
    )


async def get_kite_access_session_provider(
    session: AsyncSession = Depends(get_session),
) -> KiteAccessSessionProvider:
    """Build the internal-only Kite access session provider."""
    return KiteAccessSessionProvider(
        settings=settings,
        session_store=SQLAlchemySessionStore(session),
        token_cipher=_build_token_cipher(),
    )


async def get_instrument_sync_service(
    session: AsyncSession = Depends(get_session),
    session_provider: KiteAccessSessionProvider = Depends(get_kite_access_session_provider),
) -> InstrumentSyncService:
    """Build the instrument sync service."""
    return InstrumentSyncService(
        settings=settings,
        market_client=KiteConnectMarketClient(),
        repository=SQLAlchemyMarketDataRepository(session),
        session_provider=session_provider,
    )


async def get_market_data_stream_service() -> MarketDataStreamService:
    """Return a process-local stream controller for P04."""
    global _market_data_stream_service
    if _market_data_stream_service is None:
        _market_data_stream_service = MarketDataStreamService(
            settings=settings,
            market_client=KiteConnectMarketClient(),
            repository=SessionFactoryMarketDataRepository(async_session_factory),
            session_provider=KiteAccessSessionProvider(
                settings=settings,
                session_store=SessionFactorySessionStore(async_session_factory),
                token_cipher=_build_token_cipher(),
            ),
        )
    return _market_data_stream_service
