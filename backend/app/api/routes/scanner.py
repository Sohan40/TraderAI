"""Operator-protected deterministic scanner routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_scanner_auto_loop_service,
    get_scanner_service,
    require_operator_token,
)
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.exceptions import (
    ScannerAutoLoopBusyError,
    ScannerAutoLoopDisabledError,
    ScannerAutoLoopRunningError,
    ScannerConfigError,
    ScannerDisabledError,
    ScannerInputError,
)
from app.scanners.service import ScannerService
from app.universe.exceptions import SelectedUniverseMissingError

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


@router.post("/run-batch")
async def scanner_run_batch(
    symbols: list[str] | None = Query(default=None),
    timeframe: str = Query(default="1minute"),
    store_rejections: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    use_latest_universe: bool = Query(default=False),
    service: ScannerService = Depends(get_scanner_service),
) -> dict[str, object]:
    """Scan configured or explicit symbols using stored completed candles."""
    try:
        result = await service.run_batch(
            symbols=symbols,
            timeframe=timeframe,
            store_rejections=store_rejections,
            dry_run=dry_run,
            use_latest_universe=use_latest_universe,
        )
    except ScannerDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="scanner disabled") from exc
    except ScannerInputError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except SelectedUniverseMissingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ScannerConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="scanner config invalid",
        ) from exc
    return result.as_dict()


@router.post("/auto-loop/start")
async def scanner_auto_loop_start(
    service: ScannerAutoLoopService = Depends(get_scanner_auto_loop_service),
) -> dict[str, object]:
    """Start the disabled-by-default scanner loop."""
    try:
        return await service.start()
    except (ScannerDisabledError, ScannerAutoLoopDisabledError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ScannerAutoLoopRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ScannerConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/auto-loop/stop")
async def scanner_auto_loop_stop(
    service: ScannerAutoLoopService = Depends(get_scanner_auto_loop_service),
) -> dict[str, object]:
    """Stop the scanner loop idempotently."""
    return await service.stop()


@router.get("/auto-loop/status")
async def scanner_auto_loop_status(
    service: ScannerAutoLoopService = Depends(get_scanner_auto_loop_service),
) -> dict[str, object]:
    """Return non-sensitive scanner loop status."""
    return service.status()


@router.post("/auto-loop/run-now")
async def scanner_auto_loop_run_now(
    service: ScannerAutoLoopService = Depends(get_scanner_auto_loop_service),
) -> dict[str, object]:
    """Run one strict auto-loop batch for controlled testing."""
    try:
        return await service.run_now()
    except (ScannerDisabledError, ScannerAutoLoopDisabledError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ScannerAutoLoopBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ScannerInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ScannerConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/signals")
async def scanner_signals(
    limit: int = Query(default=50, ge=1, le=200),
    service: ScannerService = Depends(get_scanner_service),
) -> list[dict[str, object]]:
    """List immutable non-sensitive scanner observations."""
    return await service.list_signals(limit=limit)
