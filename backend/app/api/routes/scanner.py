"""Operator-protected deterministic scanner routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_scanner_service, require_operator_token
from app.scanners.exceptions import ScannerConfigError, ScannerDisabledError, ScannerInputError
from app.scanners.service import ScannerService

router = APIRouter(
    prefix="/api/v1/scanner",
    tags=["scanner"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/status")
async def scanner_status(service: ScannerService = Depends(get_scanner_service)) -> dict[str, object]:
    """Return non-sensitive scanner status."""
    return await service.status()


@router.post("/run-once")
async def scanner_run_once(
    symbol: str | None = Query(default=None),
    timeframe: str = Query(default="1minute"),
    service: ScannerService = Depends(get_scanner_service),
) -> dict[str, object]:
    """Run deterministic scanners over stored completed candles only."""
    try:
        result = await service.run_once(symbol=symbol, timeframe=timeframe)
    except ScannerDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="scanner disabled") from exc
    except ScannerInputError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported timeframe") from exc
    except ScannerConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="scanner config invalid") from exc
    return {
        "evaluated": result.evaluated,
        "inserted": result.inserted,
        "duplicates": result.duplicates,
        "candidates": result.candidates,
        "rejected": result.rejected,
        "veto_counts": result.veto_counts,
    }


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(default=50, ge=1, le=200),
    service: ScannerService = Depends(get_scanner_service),
) -> list[dict[str, object]]:
    """List immutable non-sensitive scanner observations."""
    return await service.list_signals(limit=limit)
