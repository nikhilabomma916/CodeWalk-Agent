from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - health status, not a password
    FAIL = "fail"


class OverallStatus(StrEnum):
    OK = "ok"
    """Alive and every registered dependency check passed."""
    DEGRADED = "degraded"
    """Alive, but an optional (non-required) dependency check failed."""
    UNAVAILABLE = "unavailable"
    """A required dependency check failed; the service cannot serve traffic."""


class DependencyCheckResult(BaseModel):
    name: str = Field(description="Dependency identifier, e.g. 'database'.")
    status: CheckStatus
    required: bool = Field(description="Whether a failure makes the service not ready.")
    latency_ms: float = Field(ge=0)
    detail: str | None = Field(default=None, description="Client-safe failure reason.")


class LivenessResponse(BaseModel):
    status: OverallStatus = OverallStatus.OK


class HealthResponse(BaseModel):
    status: OverallStatus
    service: str
    version: str
    environment: str
    timestamp: datetime
    uptime_seconds: float = Field(ge=0)
    checks: list[DependencyCheckResult] = Field(
        description=(
            "Results of every dependency check that is actually registered. "
            "Dependencies that are not yet integrated are not listed and are never reported healthy."
        )
    )


class ApiInfoResponse(BaseModel):
    name: str
    version: str
    api_version: str
    environment: str
    docs_url: str | None = Field(description="Interactive API docs path, when enabled.")
