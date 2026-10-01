"""Project business rules."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import Project
from app.repositories.projects import ProjectRepository
from app.schemas.projects import ProjectCreate, ProjectResponse, ProjectUpdate, WorkspaceInfo
from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES
from app.utils.paths import resolve_within


class WorkspaceDisabledError(AppError):
    status_code = 400
    code = "workspace_disabled"

    def __init__(self) -> None:
        super().__init__("Linking server folders is disabled (CODEWALK_WORKSPACE_ROOT is not set).")


def to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        root_path=project.root_path,
        read_only=project.root_path is not None,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def workspace_info(settings: Settings) -> WorkspaceInfo:
    root = settings.workspace_root
    if root is None:
        return WorkspaceInfo(enabled=False, folders=[])
    folders = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir()
        and not entry.is_symlink()
        and entry.name not in DEFAULT_IGNORED_DIRECTORIES
        and not entry.name.startswith(".")
    )
    return WorkspaceInfo(enabled=True, folders=folders)


class ProjectService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)

    def resolve_root(self, root_path: str) -> Path:
        """Absolute folder for a linked project; never outside the workspace root."""
        if self.settings.workspace_root is None:
            raise WorkspaceDisabledError()
        folder = resolve_within(self.settings.workspace_root, root_path)
        if not folder.is_dir():
            raise NotFoundError("The linked folder does not exist in the workspace.", code="folder_not_found")
        return folder

    def get(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found.", code="project_not_found")
        return project

    def list(self, *, limit: int, offset: int) -> tuple[Sequence[Project], int]:
        return self.projects.list(limit=limit, offset=offset)

    def _ensure_name_available(self, name: str, *, exclude: uuid.UUID | None = None) -> None:
        existing = self.projects.get_by_name(name)
        if existing is not None and existing.id != exclude:
            raise ConflictError(f'A project named "{existing.name}" already exists.', code="project_exists")

    def create(self, data: ProjectCreate) -> Project:
        self._ensure_name_available(data.name)
        if data.root_path is not None:
            self.resolve_root(data.root_path)
        try:
            project = self.projects.create(
                name=data.name, description=data.description, root_path=data.root_path
            )
            self.session.commit()
        except IntegrityError:  # concurrent create with the same name
            self.session.rollback()
            raise ConflictError(
                f'A project named "{data.name}" already exists.', code="project_exists"
            ) from None
        return project

    def update(self, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("name") is None:
            changes.pop("name", None)
        if "name" in changes:
            self._ensure_name_available(changes["name"], exclude=project.id)
        try:
            self.projects.update(project, **changes)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError("A project with that name already exists.", code="project_exists") from None
        self.session.refresh(project)
        return project

    def delete(self, project_id: uuid.UUID) -> None:
        self.projects.delete(self.get(project_id))
        self.session.commit()
