"""Shared FastAPI dependencies."""

from hmac import compare_digest

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.kite_auth_service import KiteAuthService, RedisStateStore
from app.broker.kite_client import KiteConnectAuthClient
from app.broker.session_store import SQLAlchemySessionStore
from app.broker.token_cipher import TokenCipher
from app.cache.redis import get_redis_client
from app.core.config import settings
from app.db.session import get_session


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
