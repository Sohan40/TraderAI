"""Operator-protected Kite authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_kite_auth_service, require_operator_token
from app.broker.exceptions import (
    KiteAuthDisabledError,
    KiteConfigError,
    KiteSessionError,
    KiteStateError,
)
from app.broker.kite_auth_service import KiteAuthService

router = APIRouter(prefix="/api/v1/broker/kite", tags=["kite-auth"])


@router.post("/login-url", dependencies=[Depends(require_operator_token)])
async def create_login_url(
    service: KiteAuthService = Depends(get_kite_auth_service),
) -> dict[str, str]:
    """Create a Kite login URL without exposing secrets."""
    try:
        return await service.create_login_url()
    except KiteAuthDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="kite auth disabled") from exc
    except KiteConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="kite auth configuration incomplete",
        ) from exc


@router.get("/callback")
async def handle_callback(
    request_token: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: KiteAuthService = Depends(get_kite_auth_service),
) -> dict[str, object]:
    """Handle Zerodha's redirect after validating callback state."""
    try:
        return await service.handle_callback(request_token=request_token, state=state)
    except KiteStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid kite callback") from exc
    except KiteAuthDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="kite auth disabled") from exc
    except KiteConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="kite auth configuration incomplete",
        ) from exc
    except KiteSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="kite session exchange failed",
        ) from exc


@router.get("/session/status", dependencies=[Depends(require_operator_token)])
async def get_session_status(
    service: KiteAuthService = Depends(get_kite_auth_service),
) -> dict[str, object]:
    """Return non-sensitive Kite session status."""
    return await service.get_status()


@router.post("/session/logout", dependencies=[Depends(require_operator_token)])
async def logout_session(
    service: KiteAuthService = Depends(get_kite_auth_service),
) -> dict[str, object]:
    """Invalidate and mark the local Kite session inactive."""
    try:
        return await service.logout()
    except KiteAuthDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="kite auth disabled") from exc
    except KiteConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="kite auth configuration incomplete",
        ) from exc
    except KiteSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="kite logout failed",
        ) from exc
