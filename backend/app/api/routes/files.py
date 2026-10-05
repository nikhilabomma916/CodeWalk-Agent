from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from pydantic import BaseModel

from app.api.deps import AnalysisServiceDep, FileServiceDep
from app.db.models import Analysis, ProjectFile
from app.schemas.analysis import AnalysisRecord, AnalysisRecordDetail
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse
from app.schemas.projects import (
    CodeFileCreate,
    FileCreate,
    FileDetail,
    FileImportRequest,
    FileImportSkipped,
    FileMetadata,
    FileUpdate,
    FileVersionDetail,
    FileVersionSummary,
    PathChangeResponse,
    PathDeleteRequest,
    PathRenameRequest,
)

router = APIRouter(
    prefix="/projects/{project_id}/files",
    tags=["files"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project or file not found."},
        409: {"model": ErrorResponse, "description": "Path exists, or the project is read-only."},
        413: {"model": ErrorResponse, "description": "Content exceeds CODEWALK_MAX_SOURCE_BYTES."},
        503: {"model": ErrorResponse, "description": "Database not configured or unavailable."},
    },
)


class FileSaveResponse(BaseModel):
    file: FileDetail
    analysis: AnalysisRecord | None = None


def _metadata(record: ProjectFile) -> dict[str, object]:
    return {field: getattr(record, field) for field in FileMetadata.model_fields if field != "has_content"}


def to_metadata(record: ProjectFile) -> FileMetadata:
    # has_content is derived from content_hash (content itself is deferred in listings).
    return FileMetadata.model_validate({**_metadata(record), "has_content": record.content_hash is not None})


def to_detail(record: ProjectFile) -> FileDetail:
    return FileDetail.model_validate(
        {**_metadata(record), "has_content": record.content is not None, "content": record.content}
    )


def _saved(record: ProjectFile, analysis: Analysis | None) -> FileSaveResponse:
    return FileSaveResponse(
        file=to_detail(record), analysis=AnalysisRecord.model_validate(analysis) if analysis else None
    )


@router.post(
    "",
    response_model=FileSaveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a file",
    description="Stores the file and records a static analysis of its content (never executed).",
)
def create_file(project_id: uuid.UUID, data: FileCreate, service: FileServiceDep) -> FileSaveResponse:
    return _saved(*service.create(project_id, data))


@router.post(
    "/code-file",
    response_model=FileSaveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a code file from a file name (Coding: New File)",
    description=(
        "Creates an empty file at the project root. Only a file name is accepted (no folders, '.', '..', "
        "absolute paths, or control characters) with a programming/development extension (.py, .js, .ts, "
        ".java, .c, .cpp, .cs, .go, .rs, .html, .css, .sql, .json, .yaml, .md, ...). 409 `file_exists` if "
        "it already exists (never overwritten); 422 `invalid_file_name` / `unsupported_file_type`."
    ),
)
def create_code_file(
    project_id: uuid.UUID, data: CodeFileCreate, service: FileServiceDep
) -> FileSaveResponse:
    return _saved(*service.create_code_file(project_id, data.name))


class FileImportResponse(BaseModel):
    created: list[FileMetadata]
    skipped: list[FileImportSkipped]


@router.post(
    "/import",
    response_model=FileImportResponse,
    summary="Upload a batch of files from a local folder",
    description=(
        "Stores up to 100 files per request (the client sends a folder in batches). Each file is checked "
        "on its own: unsafe paths, credentials files (.env, keys), dependency/build folders, files over "
        "CODEWALK_MAX_SOURCE_BYTES, existing paths (never overwritten), and files beyond the project "
        "file limit are skipped and listed with a reason. The stored files of a batch are committed "
        "together. Run `POST /projects/{id}/analyze` afterwards for project intelligence."
    ),
)
def import_files(
    project_id: uuid.UUID, data: FileImportRequest, service: FileServiceDep
) -> FileImportResponse:
    created, skipped = service.import_files(project_id, data.files)
    return FileImportResponse(created=[to_metadata(record) for record in created], skipped=list(skipped))


@router.post(
    "/rename-path",
    response_model=PathChangeResponse,
    summary="Rename or move a file or a folder",
    description=(
        "Renames/moves one file, or a folder with every file in it, in one transaction (each file "
        "records a new version with its new path). 409 `file_exists` if a target path is taken, 422 "
        "`invalid_move` for a folder moved into itself, 404 `path_not_found`."
    ),
)
def rename_path(
    project_id: uuid.UUID, data: PathRenameRequest, service: FileServiceDep
) -> PathChangeResponse:
    return PathChangeResponse(paths=list(service.rename_path(project_id, data.from_path, data.to_path)))


@router.post(
    "/delete-path",
    response_model=PathChangeResponse,
    summary="Delete a file or a folder",
    description="Deletes one file, or a folder with every file in it, in one transaction.",
)
def delete_path(
    project_id: uuid.UUID, data: PathDeleteRequest, service: FileServiceDep
) -> PathChangeResponse:
    return PathChangeResponse(paths=list(service.delete_path(project_id, data.path)))


@router.get("", response_model=Page[FileMetadata], summary="List files (metadata only, ordered by path)")
def list_files(
    project_id: uuid.UUID,
    service: FileServiceDep,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FileMetadata]:
    items, total = service.list(project_id, limit=limit, offset=offset)
    return Page(items=[to_metadata(r) for r in items], total=total, limit=limit, offset=offset)


@router.get("/{file_id}", response_model=FileDetail, summary="Get a file with its content")
def get_file(project_id: uuid.UUID, file_id: uuid.UUID, service: FileServiceDep) -> FileDetail:
    return to_detail(service.get(project_id, file_id))


@router.patch(
    "/{file_id}",
    response_model=FileSaveResponse,
    summary="Update content and/or rename",
    description="Saving new content records a static analysis of it (history is capped per file).",
)
def update_file(
    project_id: uuid.UUID, file_id: uuid.UUID, data: FileUpdate, service: FileServiceDep
) -> FileSaveResponse:
    return _saved(*service.update(project_id, file_id, data))


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a file")
def delete_file(project_id: uuid.UUID, file_id: uuid.UUID, service: FileServiceDep) -> Response:
    service.delete(project_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{file_id}/analyses",
    response_model=AnalysisRecordDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a stored file and record the result",
)
def analyze_file(
    project_id: uuid.UUID, file_id: uuid.UUID, files: FileServiceDep, analyses: AnalysisServiceDep
) -> AnalysisRecordDetail:
    return AnalysisRecordDetail.build(*analyses.analyze_stored_file(files.get(project_id, file_id)))


@router.get(
    "/{file_id}/versions",
    response_model=Page[FileVersionSummary],
    summary="Saved versions of a file (newest first, without content)",
)
def list_versions(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    service: FileServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FileVersionSummary]:
    items, total = service.list_versions(project_id, file_id, limit=limit, offset=offset)
    return Page(
        items=[FileVersionSummary.model_validate(v) for v in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{file_id}/versions/{version}", response_model=FileVersionDetail, summary="One version with content"
)
def get_version(
    project_id: uuid.UUID, file_id: uuid.UUID, version: Annotated[int, Path(ge=1)], service: FileServiceDep
) -> FileVersionDetail:
    return FileVersionDetail.model_validate(service.get_version(project_id, file_id, version))


@router.post(
    "/{file_id}/versions/{version}/restore",
    response_model=FileSaveResponse,
    summary="Make an earlier version the current content",
    description="Saved as a new version (so a restore can itself be undone) and analyzed like any save.",
)
def restore_version(
    project_id: uuid.UUID, file_id: uuid.UUID, version: Annotated[int, Path(ge=1)], service: FileServiceDep
) -> FileSaveResponse:
    return _saved(*service.restore_version(project_id, file_id, version))
