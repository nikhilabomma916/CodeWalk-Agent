"""Deterministic project insights (Module 17): architecture, dependency impact, and references.

Owner-only, computed from the stored project (no AI, nothing executed), bounded.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter

from app.api.deps import SearchServiceDep
from app.core.exceptions import NotFoundError
from app.core.metrics import METRICS
from app.schemas.errors import ErrorResponse
from app.schemas.insights import ImpactRequest, ReferencesRequest
from app.services import insights
from app.services.insights import ArchitectureReport, ImpactReport, ReferenceReport

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["insights"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project or file not found (or not yours)."},
    },
)


@router.get(
    "/architecture",
    response_model=ArchitectureReport,
    summary="Architecture summary of a project",
    description=(
        "Components (top-level folders), file roles, resolved import links between components, entry "
        "points, HTTP routes, and database models, derived from the stored files. Deterministic."
    ),
)
def project_architecture(project_id: uuid.UUID, search: SearchServiceDep) -> ArchitectureReport:
    _, index = search.project_index(project_id)
    started = time.perf_counter()
    report = insights.architecture(index)
    METRICS.observe("architecture_analysis", time.perf_counter() - started)
    return report


@router.post(
    "/impact",
    response_model=ImpactReport,
    summary="What may break if a file or symbol changes",
    description=(
        "Direct and indirect dependents (resolved imports), references inside the file, possible "
        "references elsewhere (same name, no import), related tests and HTTP routes. Each relationship is "
        "labelled `confirmed` or `possible`. Deterministic; there is no call graph."
    ),
)
def project_impact(project_id: uuid.UUID, request: ImpactRequest, search: SearchServiceDep) -> ImpactReport:
    _, index = search.project_index(project_id)
    if request.file_path not in index.files:
        raise NotFoundError("File not found in this project.", code="file_not_found")
    started = time.perf_counter()
    report = insights.impact(index, request.file_path, request.symbol)
    METRICS.observe("impact_analysis", time.perf_counter() - started)
    return report


@router.post(
    "/references",
    response_model=ReferenceReport,
    summary="Definitions and references of a name",
    description="Where a symbol is defined and where its name occurs, labelled `confirmed` or `possible`.",
)
def project_references(
    project_id: uuid.UUID, request: ReferencesRequest, search: SearchServiceDep
) -> ReferenceReport:
    _, index = search.project_index(project_id)
    return insights.references(index, request.name)
