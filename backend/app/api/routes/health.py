from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.errors import ErrorResponse
from app.schemas.health import HealthResponse, LivenessResponse, OverallStatus

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    summary="Service health report",
    description=(
        "Reports liveness, uptime, and the result of every registered dependency check. "
        "Returns **503** when a required dependency check fails."
    ),
    responses={503: {"model": HealthResponse, "description": "A required dependency is failing."}},
)
async def health(service: HealthServiceDep, response: Response) -> HealthResponse:
    report = await service.report()
    if report.status is OverallStatus.UNAVAILABLE:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Returns 200 whenever the process can serve requests. Runs no dependency checks.",
)
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="Runs dependency checks; 200 when ready to serve traffic, 503 otherwise.",
    responses={503: {"model": HealthResponse, "description": "Not ready."}, 500: {"model": ErrorResponse}},
)
async def ready(service: HealthServiceDep, response: Response) -> HealthResponse:
    return await health(service, response)
