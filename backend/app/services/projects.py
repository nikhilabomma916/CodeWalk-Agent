"""Project business rules."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import ActivityType, Project, ProjectOrigin, User
from app.repositories.projects import ProjectRepository, ProjectStatsRow
from app.schemas.projects import (
    LanguageCount,
    ProjectCreate,
    ProjectResponse,
    ProjectStats,
    ProjectUpdate,
    WorkspaceInfo,
)
from app.services.activity import ActivityRecorder
from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES
from app.utils.paths import resolve_within


class WorkspaceDisabledError(AppError):
    status_code = 400
    code = "workspace_disabled"

    def __init__(self) -> None:
        super().__init__("Linking server folders is disabled (CODEWALK_WORKSPACE_ROOT is not set).")


def to_response(project: Project, stats: ProjectStatsRow) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        root_path=project.root_path,
        read_only=project.root_path is not None,
        origin=project.origin.value,
        created_at=project.created_at,
        updated_at=project.updated_at,
        stats=ProjectStats(
            file_count=stats.file_count,
            total_bytes=stats.total_bytes,
            total_lines=stats.total_lines,
            languages=[
                LanguageCount(language=language, files=files)
                for language, files in sorted(stats.languages.items(), key=lambda item: (-item[1], item[0]))
            ],
            last_analyzed_at=stats.last_analyzed_at,
        ),
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
    """Projects of one user. Other users' projects are reported as not found."""

    def __init__(self, session: Session, settings: Settings, owner: User) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.projects = ProjectRepository(session)
        self.activity = ActivityRecorder(session, owner)

    def responses(self, projects: Sequence[Project]) -> list[ProjectResponse]:
        stats = self.projects.stats([project.id for project in projects])
        return [to_response(project, stats[project.id]) for project in projects]

    def response(self, project: Project) -> ProjectResponse:
        return self.responses([project])[0]

    def resolve_root(self, root_path: str) -> Path:
        """Absolute folder for a linked project; never outside the workspace root."""
        if self.settings.workspace_root is None:
            raise WorkspaceDisabledError()
        folder = resolve_within(self.settings.workspace_root, root_path)
        if not folder.is_dir():
            raise NotFoundError("The linked folder does not exist in the workspace.", code="folder_not_found")
        return folder

    def get(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(self.owner.id, project_id)
        if project is None:
            # Answered as "not found" either way; the audit log records whether the project exists
            # and belongs to someone else (a cross-user access attempt).
            foreign = self.session.scalar(select(Project.id).where(Project.id == project_id)) is not None
            audit(
                "project_access_denied" if foreign else "project_not_found",
                level=logging.WARNING if foreign else logging.INFO,
                user=self.owner.id,
                project=project_id,
            )
            raise NotFoundError("Project not found.", code="project_not_found")
        return project

    def list(
        self, *, limit: int, offset: int, origin: ProjectOrigin | None = None
    ) -> tuple[Sequence[Project], int]:
        return self.projects.list(self.owner.id, limit=limit, offset=offset, origin=origin)

    def _ensure_name_available(self, name: str, *, exclude: uuid.UUID | None = None) -> None:
        existing = self.projects.get_by_name(self.owner.id, name)
        if existing is not None and existing.id != exclude:
            raise ConflictError(f'A project named "{existing.name}" already exists.', code="project_exists")

    def available_name(self, wanted: str, *, suffix: str = "editable") -> str:
        """``wanted`` if free, else "wanted (editable)", "wanted (editable 2)", ... within 100 chars."""
        candidates = [wanted] + [f" ({suffix})"] + [f" ({suffix} {n})" for n in range(2, 100)]
        for i, candidate in enumerate(candidates):
            name = candidate if i == 0 else wanted[: 100 - len(candidate)].rstrip() + candidate
            if self.projects.get_by_name(self.owner.id, name) is None:
                return name
        raise ConflictError(f'Too many projects are named like "{wanted}".', code="project_exists")

    def create(self, data: ProjectCreate) -> Project:
        self._ensure_name_available(data.name)
        if data.root_path is not None:
            self.resolve_root(data.root_path)
        try:
            project = self.projects.create(
                owner_id=self.owner.id,
                name=data.name,
                description=data.description,
                root_path=data.root_path,
                origin=ProjectOrigin(data.origin),
            )
            self.activity.record(
                ActivityType.PROJECT_CREATED,
                project,
                details={"linked_folder": data.root_path} if data.root_path else None,
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
        changes = {key: value for key, value in changes.items() if getattr(project, key) != value}
        if not changes:
            return project
        previous_name = project.name
        try:
            self.projects.update(project, **changes)
            details: dict[str, object] = {"changed": sorted(changes)}
            if "name" in changes:
                details["renamed_from"] = previous_name
            self.activity.record(ActivityType.PROJECT_UPDATED, project, details=details)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError("A project with that name already exists.", code="project_exists") from None
        self.session.refresh(project)
        return project

    def delete(self, project_id: uuid.UUID) -> None:
        project = self.get(project_id)
        self.activity.record(ActivityType.PROJECT_DELETED, project, keep_project_link=False)
        self.projects.delete(project)
        self.session.commit()
