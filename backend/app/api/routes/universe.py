"""Operator-protected deterministic universe-selection routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_universe_selection_service, require_operator_token
from app.universe.exceptions import UniverseInputError, UniverseSelectionDisabledError
from app.universe.service import UniverseSelectionService

router = APIRouter(
    prefix="/api/v1/universe",
    tags=["universe"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/status")
async def universe_status(
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> dict[str, object]:
    return await service.status()


@router.get("/pool/validate")
async def validate_universe_pool(
    symbols: list[str] | None = Query(default=None),
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> dict[str, object]:
    return await service.validate_pool(symbols)


@router.post("/select")
async def select_universe(
    limit: int | None = Query(default=None, ge=1),
    timeframe: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
    include_excluded: bool = Query(default=True),
    use_current_session: bool = Query(default=True),
    min_candles: int | None = Query(default=None, ge=1),
    symbols: list[str] | None = Query(default=None),
    stale_policy: str | None = Query(default=None),
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> dict[str, object]:
    try:
        run = await service.select(
            limit=limit,
            timeframe=timeframe,
            dry_run=dry_run,
            include_excluded=include_excluded,
            use_current_session=use_current_session,
            min_candles=min_candles,
            symbols=symbols,
            stale_policy=stale_policy,
        )
    except UniverseSelectionDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UniverseInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return run.as_dict()


@router.get("/latest")
async def latest_universe(
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> dict[str, object]:
    run = await service.latest()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="selected universe missing",
        )
    return run.as_dict()


@router.get("/runs")
async def universe_runs(
    limit: int = Query(default=20, ge=1, le=100),
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> list[dict[str, object]]:
    return [run.as_dict() for run in await service.list_runs(limit=limit)]


@router.get("/runs/{run_id}")
async def universe_run(
    run_id: str,
    service: UniverseSelectionService = Depends(get_universe_selection_service),
) -> dict[str, object]:
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="universe run not found")
    return run.as_dict()
