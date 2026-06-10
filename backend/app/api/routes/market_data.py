"""Operator-protected read-only market-data routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_instrument_sync_service,
    get_market_data_stream_service,
    get_stream_readiness_service,
    get_watchlist_validation_service,
    require_operator_token,
)
from app.market_data.exceptions import (
    InstrumentSyncDisabledError,
    MarketDataDisabledError,
    MarketDataSessionError,
    MarketDataStreamError,
    WatchlistError,
)
from app.market_data.instrument_sync import InstrumentSyncService
from app.market_data.stream_readiness import StreamReadinessService
from app.market_data.watchlist_validation import WatchlistValidationService
from app.market_data.websocket_service import MarketDataStreamService

router = APIRouter(
    prefix="/api/v1/market-data",
    tags=["market-data"],
    dependencies=[Depends(require_operator_token)],
)


@router.post("/instruments/sync")
async def sync_instruments(
    service: InstrumentSyncService = Depends(get_instrument_sync_service),
) -> dict[str, object]:
    """Synchronize only configured read-only instruments."""
    try:
        result = await service.sync()
    except InstrumentSyncDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="instrument sync disabled") from exc
    except WatchlistError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "watchlist_invalid", "message": str(exc)},
        ) from exc
    except MarketDataSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="active kite session required",
        ) from exc
    return {
        "fetched": result.fetched,
        "inserted": result.inserted,
        "updated": result.updated,
        "skipped": result.skipped,
        "failed": result.failed,
        "watchlist_validation": result.watchlist_validation or {},
    }


@router.get("/watchlist/validate")
async def validate_watchlist(
    service: WatchlistValidationService = Depends(get_watchlist_validation_service),
) -> dict[str, object]:
    """Validate configured watchlist using config and local DB only."""
    return (await service.validate()).as_dict()


@router.get("/stream/readiness")
async def stream_readiness(
    service: StreamReadinessService = Depends(get_stream_readiness_service),
) -> dict[str, object]:
    """Explain whether the read-only stream can be started."""
    return await service.readiness()


@router.get("/status")
async def market_data_status(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> dict[str, object]:
    """Return non-sensitive market-data status."""
    return service.status_dict()


@router.post("/stream/start")
async def start_stream(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
    readiness_service: StreamReadinessService = Depends(get_stream_readiness_service),
) -> dict[str, object]:
    """Start read-only quote streaming after all safety gates pass."""
    readiness = await readiness_service.readiness()
    if not readiness["can_start_stream"] and not readiness["stream_already_running"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "stream_not_ready",
                "errors": readiness["errors"],
                "missing_symbols": readiness["missing_symbols"],
                "inactive_symbols": readiness["inactive_symbols"],
                "recommended_next_action": readiness["recommended_next_action"],
            },
        )
    try:
        return await service.start()
    except MarketDataDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="market data disabled") from exc
    except WatchlistError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "watchlist_invalid", "message": str(exc)},
        ) from exc
    except MarketDataSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="active kite session required",
        ) from exc
    except MarketDataStreamError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="stream start failed") from exc


@router.post("/stream/stop")
async def stop_stream(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> dict[str, object]:
    """Stop the read-only quote stream."""
    return await service.stop()


@router.get("/stream/status")
async def stream_status(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> dict[str, object]:
    """Return non-sensitive quote stream status."""
    return service.status_dict()
