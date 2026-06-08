"""Operator-protected paper-trading routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_paper_service, require_operator_token
from app.paper.exceptions import (
    LiveModeNotImplementedError,
    PaperConfigError,
    PaperDisabledError,
    PaperModeDisabledError,
)
from app.paper.service import PaperService

router = APIRouter(
    prefix="/api/v1/paper",
    tags=["paper"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/status")
async def paper_status(service: PaperService = Depends(get_paper_service)) -> dict[str, object]:
    """Return non-sensitive paper engine status."""
    return await service.status()


@router.post("/run-replay")
async def paper_run_replay(
    symbol: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    service: PaperService = Depends(get_paper_service),
) -> dict[str, object]:
    """Run deterministic paper replay from stored P05 candidates and candles."""
    try:
        summary = await service.run_replay(
            symbol=symbol,
            start=from_time,
            end=to_time,
            limit=limit,
        )
    except LiveModeNotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except PaperDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="paper disabled") from exc
    except PaperModeDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PaperConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return summary.as_dict()


@router.get("/report")
async def paper_report(
    limit: int = Query(default=1000, ge=1, le=10_000),
    service: PaperService = Depends(get_paper_service),
) -> dict[str, object]:
    """Return aggregate paper journal report."""
    return await service.report(limit=limit)


@router.get("/trades")
async def paper_trades(
    limit: int = Query(default=100, ge=1, le=500),
    service: PaperService = Depends(get_paper_service),
) -> list[dict[str, object]]:
    """Return bounded recent paper trade/rejection outcomes."""
    return await service.trades(limit=limit)
