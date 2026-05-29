"""Operator-protected read-only market-data routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_instrument_sync_service,
    get_market_data_stream_service,
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
from app.market_data.websocket_service import MarketDataStreamService

router = APIRouter(
    prefix="/api/v1/market-data",
    tags=["market-data"],
    dependencies=[Depends(require_operator_token)],
)


@router.post("/instruments/sync")
async def sync_instruments(
    service: InstrumentSyncService = Depends(get_instrument_sync_service),
) -> dict[str, int]:
    """Synchronize only configured read-only instruments."""
    try:
        result = await service.sync()
    except InstrumentSyncDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="instrument sync disabled") from exc
    except WatchlistError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid watchlist") from exc
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
    }


@router.get("/status")
async def market_data_status(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> dict[str, object]:
    """Return non-sensitive market-data status."""
    return service.status_dict()


@router.post("/stream/start")
async def start_stream(
    service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> dict[str, object]:
    """Start read-only quote streaming after all safety gates pass."""
    try:
        return await service.start()
    except MarketDataDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="market data disabled") from exc
    except WatchlistError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid watchlist") from exc
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
