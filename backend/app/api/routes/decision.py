"""Operator-protected P07 decision routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_decision_automation_service,
    get_decision_service,
    require_operator_token,
)
from app.decision.automation import DecisionAutomationService
from app.decision.exceptions import (
    DecisionConfigError,
    DecisionDisabledError,
    DecisionSignalIneligibleError,
    DecisionSignalNotFoundError,
)
from app.decision.service import DecisionService

router = APIRouter(
    prefix="/api/v1/decision",
    tags=["decision"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/status")
async def decision_status(
    service: DecisionService = Depends(get_decision_service),
) -> dict[str, object]:
    return await service.status()


@router.post("/evaluate")
async def decision_evaluate(
    signal_id: int = Query(gt=0),
    force: bool = Query(default=False),
    service: DecisionService = Depends(get_decision_service),
) -> dict[str, object]:
    try:
        return (await service.evaluate(signal_id=signal_id, force=force)).as_dict()
    except DecisionDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DecisionSignalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DecisionSignalIneligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except DecisionConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/recommendations")
async def decision_recommendations(
    limit: int = Query(default=100, ge=1, le=500),
    service: DecisionService = Depends(get_decision_service),
) -> list[dict[str, object]]:
    return await service.recommendations(limit=limit)


@router.get("/auto-status")
async def decision_auto_status(
    service: DecisionAutomationService = Depends(get_decision_automation_service),
) -> dict[str, object]:
    return service.status()


@router.post("/evaluate-latest")
async def decision_evaluate_latest(
    limit: int = Query(default=5, ge=1, le=50),
    service: DecisionAutomationService = Depends(get_decision_automation_service),
) -> dict[str, object]:
    try:
        return await service.evaluate_latest(limit=limit)
    except DecisionDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DecisionConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
