from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import ProjectFilePath, ProjectName, RelativePath


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: str | None = Field(default=None, max_length=2000)
    root_path: RelativePath | None = Field(
        default=None,
        description=(
            "Folder relative to the server's CODEWALK_WORKSPACE_ROOT to link. Linked projects are "
            "populated by scanning and are read-only through the file API."
        ),
    )
    origin: Literal["workspace", "upload"] = Field(
        default="workspace",
        description="'upload' for a folder uploaded from the developer's computer (Uploads area).",
    )

    @model_validator(mode="after")
    def _upload_is_not_linked(self) -> ProjectCreate:
        if self.origin == "upload" and self.root_path is not None:
            raise ValueError("An uploaded project cannot be linked to a server folder.")
        return self


class EditableCopyRequest(BaseModel):
    """Import an uploaded folder into Coding: an editable copy; the upload itself is kept unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = Field(
        default=None, description="Name of the new project (default: the upload's, made unique)."
    )


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    description: str | None = Field(default=None, max_length=2000)


class LanguageCount(BaseModel):
    language: str
    files: int


class ProjectStats(BaseModel):
    """Computed from the stored files and analyses (no analysis is run to produce it)."""

    file_count: int
    total_bytes: int
    total_lines: int
    languages: list[LanguageCount] = Field(description="Files per language, most common first.")
    last_analyzed_at: datetime | None = Field(description="When project intelligence last ran.")


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    root_path: str | None
    read_only: bool = Field(description="True for folder-linked projects (files come from scanning).")
    origin: Literal["workspace", "upload"] = Field(
        description="'upload' for a folder uploaded from the developer's computer."
    )
    created_at: datetime
    updated_at: datetime
    stats: ProjectStats


class FileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: ProjectFilePath
    content: str = ""


class CodeFileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Checked by the service (file name only, allowed extension) so the error explains the rule.
    name: str = Field(max_length=1024, description="A file name such as main.py; no folders.")


MAX_IMPORT_FILES_PER_REQUEST = 100


class FileImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Validated per file by the service, so one bad path is reported instead of rejecting the batch.
    path: str = Field(min_length=1, max_length=1024)
    content: str


class FileImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[FileImportItem] = Field(min_length=1, max_length=MAX_IMPORT_FILES_PER_REQUEST)


class FileImportSkipped(BaseModel):
    path: str
    reason: str = Field(description="invalid_path, secret, ignored, too_large, exists, duplicate, or limit.")
    message: str


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


class FileVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int = Field(description="1 for the first saved content, increasing by one per change.")
    size: int
    line_count: int
    content_hash: str
    source: str = Field(description="create | edit | restore | scan (folder rescan)")
    author_id: uuid.UUID | None
    created_at: datetime


class FileVersionDetail(FileVersionSummary):
    content: str


class WorkspaceInfo(BaseModel):
    enabled: bool = Field(description="Whether folder-linked projects can be created on this server.")
    folders: list[str] = Field(description="Top-level folders under the workspace root that can be linked.")
