"""Operator-protected local operational readiness routes."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_morning_readiness_service, require_operator_token
from app.ops.morning_readiness import MorningReadinessService

router = APIRouter(
    prefix="/api/v1/ops",
    tags=["operations"],
    dependencies=[Depends(require_operator_token)],
)


@router.get("/morning-readiness")
async def morning_readiness(
    service: MorningReadinessService = Depends(get_morning_readiness_service),
) -> dict[str, object]:
    """Aggregate local safety, watchlist, stream, and scanner readiness."""
    return await service.readiness()
