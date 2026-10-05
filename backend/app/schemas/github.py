"""GitHub integration API models (Module 20). Tokens never appear in any of them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ProjectName

# GitHub's own rules: owners are 1-39 letters, digits or single hyphens; repository names are
# letters, digits, ".", "_" and "-" (not "." or ".."); branch names are git ref names.
OwnerName = Annotated[str, Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")]
RepositoryName = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")]
BranchName = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._/-]+$")]


def _valid_ref(value: str) -> str:
    bad = (
        value.startswith(("/", "-", "."))
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "//" in value
        or "/." in value
    )
    if bad:
        raise ValueError("not a valid branch name")
    return value


class GitHubStatus(BaseModel):
    configured: bool = Field(description="The server has a GitHub OAuth app and an encryption key.")
    connected: bool
    login: str | None = None
    scopes: list[str] = Field(default_factory=list)
    private_repositories: bool = Field(description="The configured scopes allow private repositories.")
    connected_at: datetime | None = None


class GitHubConnectResponse(BaseModel):
    authorize_url: str


class GitHubRepository(BaseModel):
    id: int
    full_name: str
    owner: str
    name: str
    private: bool
    default_branch: str
    description: str | None = None
    size_kb: int = 0
    updated_at: str | None = None


class GitHubRepositoryPage(BaseModel):
    items: list[GitHubRepository]
    page: int
    has_more: bool


class GitHubBranchPage(BaseModel):
    items: list[str]
    page: int
    has_more: bool


class GitHubImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: OwnerName
    repository: RepositoryName
    branch: BranchName
    project_name: ProjectName | None = Field(default=None, description="Defaults to the repository name.")

    @field_validator("branch")
    @classmethod
    def _branch_is_a_ref(cls, value: str) -> str:
        return _valid_ref(value)

    @field_validator("owner")
    @classmethod
    def _owner_has_single_hyphens(cls, value: str) -> str:
        if "--" in value:
            raise ValueError("not a valid GitHub owner")
        return value

    @field_validator("repository")
    @classmethod
    def _repository_is_not_a_dot_name(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("not a valid repository name")
        return value


class GitHubImportSkipped(BaseModel):
    path: str
    reason: str


class GitHubImportResult(BaseModel):
    project_id: uuid.UUID
    project_name: str
    repository: str
    branch: str
    commit_sha: str
    files_imported: int
    files_skipped: int
    skipped_by_reason: dict[str, int]
    skipped: list[GitHubImportSkipped] = Field(description="The first 200 skipped files.")
    indexing: str = Field(description="completed, or failed (the files are imported either way).")
    indexed_files: int = 0


class ProjectSourceInfo(BaseModel):
    provider: str
    repository: str
    branch: str
    commit_sha: str
    private: bool
    imported_at: datetime
