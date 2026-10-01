from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DisplayName, ProjectFilePath, RelativePath


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DisplayName
    description: str | None = Field(default=None, max_length=2000)
    root_path: RelativePath | None = Field(
        default=None,
        description=(
            "Folder relative to the server's CODEWALK_WORKSPACE_ROOT to link. Linked projects are "
            "populated by scanning and are read-only through the file API."
        ),
    )


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DisplayName | None = None
    description: str | None = Field(default=None, max_length=2000)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    root_path: str | None
    read_only: bool = Field(description="True for folder-linked projects (files come from scanning).")
    created_at: datetime
    updated_at: datetime


class FileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: ProjectFilePath
    content: str = ""


class FileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: ProjectFilePath | None = Field(default=None, description="New path (rename/move).")
    content: str | None = None


class FileMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    path: str
    name: str
    language: str
    size: int
    line_count: int
    content_hash: str | None
    has_content: bool = Field(description="False for binary or oversized files, whose content is not stored.")
    created_at: datetime
    updated_at: datetime


class FileDetail(FileMetadata):
    content: str | None


class WorkspaceInfo(BaseModel):
    enabled: bool = Field(description="Whether folder-linked projects can be created on this server.")
    folders: list[str] = Field(description="Top-level folders under the workspace root that can be linked.")
