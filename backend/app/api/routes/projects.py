from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import (
    AnalysisServiceDep,
    CurrentUserDep,
    FileServiceDep,
    IntelligenceServiceDep,
    ProjectServiceDep,
    SettingsDep,
)
from app.core.exceptions import ConflictError
from app.db.models import AnalysisType, ProjectOrigin
from app.schemas.analysis import AnalysisRecord
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse
from app.schemas.projects import (
    EditableCopyRequest,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    WorkspaceInfo,
)
from app.services.project_intelligence.models import ProjectAnalysisResult
from app.services.projects import workspace_info

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project not found."},
        503: {"model": ErrorResponse, "description": "Database not configured or unavailable."},
    },
)

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/workspace", response_model=WorkspaceInfo, summary="Server workspace folders available for linking"
)
def get_workspace(settings: SettingsDep, _: CurrentUserDep) -> WorkspaceInfo:
    return workspace_info(settings)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    responses={409: {"model": ErrorResponse, "description": "A project with this name exists."}},
)
def create_project(data: ProjectCreate, service: ProjectServiceDep) -> ProjectResponse:
    return service.response(service.create(data))


@router.get("", response_model=Page[ProjectResponse], summary="List projects (most recently updated first)")
def list_projects(
    service: ProjectServiceDep,
    limit: Limit = 50,
    offset: Offset = 0,
    origin: Annotated[
        ProjectOrigin | None,
        Query(description="Only workspace projects, or only folders uploaded from a computer."),
    ] = None,
) -> Page[ProjectResponse]:
    items, total = service.list(limit=limit, offset=offset, origin=origin)
    return Page(items=service.responses(items), total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get a project")
def get_project(project_id: uuid.UUID, service: ProjectServiceDep) -> ProjectResponse:
    return service.response(service.get(project_id))


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Rename or re-describe a project",
    responses={409: {"model": ErrorResponse}},
)
def update_project(project_id: uuid.UUID, data: ProjectUpdate, service: ProjectServiceDep) -> ProjectResponse:
    return service.response(service.update(project_id, data))


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project with its files and analyses",
)
def delete_project(project_id: uuid.UUID, service: ProjectServiceDep) -> Response:
    service.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/editable-copy",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import an uploaded folder into Coding",
    description=(
        "Creates an editable Coding project with a copy of every stored file of an uploaded folder "
        "(each as version 1, analyzed like a normal save). The upload itself is kept unchanged as the "
        "original. 409 `not_an_upload` for other projects."
    ),
    responses={409: {"model": ErrorResponse, "description": "Not an upload, or the name is taken."}},
)
def editable_copy(
    project_id: uuid.UUID,
    data: EditableCopyRequest,
    projects: ProjectServiceDep,
    files: FileServiceDep,
) -> ProjectResponse:
    source = projects.get(project_id)
    if source.origin != ProjectOrigin.UPLOAD:
        raise ConflictError(
            "Only uploaded folders are imported into Coding; this project is already editable.",
            code="not_an_upload",
        )
    copy = projects.create(
        ProjectCreate(
            name=projects.available_name(data.name or source.name),
            description=f'Editable copy of the upload "{source.name}" (the upload is kept unchanged).',
        )
    )
    try:
        files.copy_files(source.id, copy.id)
    except Exception:
        # No half-copied project: remove the new one (the upload was never changed).
        projects.session.rollback()
        projects.delete(copy.id)
        raise
    return projects.response(projects.get(copy.id))


@router.post(
    "/{project_id}/analyze",
    response_model=ProjectAnalysisResult,
    summary="Analyze project structure",
    description=(
        "Runs deterministic project intelligence: files, languages, symbols, imports, relationships, "
        "and statistics. Folder-linked projects are rescanned first (new, changed, and deleted files are "
        "synced). Files that fail to parse are reported in `errors` without stopping the analysis."
    ),
)
def analyze_project(project_id: uuid.UUID, service: IntelligenceServiceDep) -> ProjectAnalysisResult:
    return service.analyze(project_id)


@router.get(
    "/{project_id}/intelligence",
    response_model=ProjectAnalysisResult,
    summary="Latest project intelligence",
    description="Built from the stored files (no rescan). 404 `not_analyzed` before the first analysis.",
)
def get_intelligence(project_id: uuid.UUID, service: IntelligenceServiceDep) -> ProjectAnalysisResult:
    return service.latest(project_id)


@router.get("/{project_id}/analyses", response_model=Page[AnalysisRecord], summary="Analysis history")
def list_analyses(
    project_id: uuid.UUID,
    projects: ProjectServiceDep,
    service: AnalysisServiceDep,
    analysis_type: AnalysisType | None = None,
    file_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[AnalysisRecord]:
    projects.get(project_id)
    items, total = service.list(
        project_id, analysis_type=analysis_type, file_id=file_id, limit=limit, offset=offset
    )
    return Page(
        items=[AnalysisRecord.model_validate(a) for a in items], total=total, limit=limit, offset=offset
    )
