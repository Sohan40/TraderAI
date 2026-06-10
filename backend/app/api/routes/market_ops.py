"""Operator-protected market operations automation controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_market_ops_orchestrator,
    get_market_ops_scheduler,
    require_operator_token,
)
from app.ops.market_ops import MarketOpsOrchestrator
from app.ops.market_ops_scheduler import (
    MarketOpsAutomationDisabledError,
    MarketOpsJobBusyError,
    MarketOpsScheduler,
)

router = APIRouter(
    prefix="/api/v1/ops/market-ops",
    tags=["market-operations"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/status")
async def market_ops_status(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return scheduler.status()


@router.post("/start")
async def market_ops_start(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    try:
        return await scheduler.start()
    except MarketOpsAutomationDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/stop")
async def market_ops_stop(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await scheduler.stop()


async def _run_job(scheduler: MarketOpsScheduler, name: str) -> dict[str, object]:
    try:
        return await scheduler.run_job(name)
    except MarketOpsJobBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/run-preopen-check")
async def market_ops_preopen(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "preopen_check")


@router.post("/run-start-stream")
async def market_ops_start_stream(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "stream_start")


@router.post("/run-verify-stream")
async def market_ops_verify_stream(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "stream_verify")


@router.post("/run-universe-selection")
async def market_ops_universe(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "universe_selection")


@router.post("/run-scanner-batch")
async def market_ops_scanner(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "scanner_batch")


@router.post("/run-stop-stream")
async def market_ops_stop_stream(
    scheduler: MarketOpsScheduler = Depends(get_market_ops_scheduler),
) -> dict[str, object]:
    return await _run_job(scheduler, "stream_stop")


@router.post("/test-notification")
async def market_ops_test_notification(
    orchestrator: MarketOpsOrchestrator = Depends(get_market_ops_orchestrator),
) -> dict[str, object]:
    return await orchestrator.test_notification()
