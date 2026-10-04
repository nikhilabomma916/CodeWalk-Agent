"""File business rules. File content is user data: stored and analyzed, never executed.

Every content change (create, edit, restore) is recorded as a new file version;
only the newest ``file_version_history_limit`` versions are kept per file.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import ActivityType, Analysis, FileVersion, FileVersionSource, Project, ProjectFile, User
from app.repositories.file_versions import FileVersionRepository
from app.repositories.files import FileRepository
from app.repositories.projects import ProjectRepository
from app.schemas.projects import FileCreate, FileUpdate
from app.services.activity import ActivityRecorder
from app.services.analysis.service import AnalysisService
from app.services.file_content import file_values
from app.services.projects import ProjectService


class ContentTooLargeError(AppError):
    status_code = 413
    code = "content_too_large"


class ProjectReadOnlyError(ConflictError):
    code = "project_read_only"

    def __init__(self) -> None:
        super().__init__("This project is linked to a server folder; its files are updated by rescanning.")


class FileService:
    def __init__(self, session: Session, settings: Settings, analysis: AnalysisService, owner: User) -> None:
        self.session = session
        self.settings = settings
        self.analysis = analysis
        self.owner = owner
        self.projects = ProjectService(session, settings, owner)
        self.project_repository = ProjectRepository(session)
        self.files = FileRepository(session)
        self.versions = FileVersionRepository(session)
        self.activity = ActivityRecorder(session, owner)

    def _writable_project(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(project_id)
        if project.root_path is not None:
            raise ProjectReadOnlyError()
        return project

    def _check_size(self, content: str) -> None:
        size = len(content.encode("utf-8"))
        if size > self.settings.max_source_bytes:
            raise ContentTooLargeError(
                f"File content is {size} bytes; the limit is {self.settings.max_source_bytes}."
            )

    def _record_version(self, record: ProjectFile, source: FileVersionSource) -> int | None:
        """Snapshot the content as a new version; returns its number (None without content)."""
        version = self.versions.add(record, source=source, author_id=self.owner.id)
        if version is None:
            return None
        self.versions.prune(record.id, keep=self.settings.file_version_history_limit)
        return version.version

    def get(self, project_id: uuid.UUID, file_id: uuid.UUID) -> ProjectFile:
        self.projects.get(project_id)
        record = self.files.get(project_id, file_id)
        if record is None:
            raise NotFoundError("File not found.", code="file_not_found")
        return record

    def list(self, project_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[ProjectFile], int]:
        self.projects.get(project_id)
        return self.files.list_metadata(project_id, limit=limit, offset=offset)

    def create(
        self, project_id: uuid.UUID, data: FileCreate, *, commit: bool = True
    ) -> tuple[ProjectFile, Analysis | None]:
        """``commit=False`` leaves the transaction open, so several saves can be committed together."""
        project = self._writable_project(project_id)
        self._check_size(data.content)
        if self.files.get_by_path(project_id, data.path) is not None:
            raise ConflictError(f"{data.path} already exists.", code="file_exists")
        try:
            record = self.files.create(project_id=project_id, **file_values(data.path, data.content))
            version = self._record_version(record, FileVersionSource.CREATE)
            analysis = self.analysis.record_file_analysis(record)[0] if data.content else None
            self.activity.record(
                ActivityType.FILE_CREATED,
                project,
                file=record,
                analysis=analysis,
                details={"version": version},
            )
            self.project_repository.touch(project)
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{data.path} already exists.", code="file_exists") from None
        return record, analysis

    def update(
        self, project_id: uuid.UUID, file_id: uuid.UUID, data: FileUpdate, *, commit: bool = True
    ) -> tuple[ProjectFile, Analysis | None]:
        """``commit=False`` leaves the transaction open, so several saves can be committed together."""
        return self._update(project_id, file_id, data, FileVersionSource.EDIT, commit=commit)

    def _update(
        self,
        project_id: uuid.UUID,
        file_id: uuid.UUID,
        data: FileUpdate,
        source: FileVersionSource,
        *,
        restored_from: int | None = None,
        commit: bool = True,
    ) -> tuple[ProjectFile, Analysis | None]:
        project = self._writable_project(project_id)
        record = self.get(project_id, file_id)
        new_path = data.path if data.path is not None and data.path != record.path else None
        if new_path is not None and self.files.get_by_path(project_id, new_path) is not None:
            raise ConflictError(f"{new_path} already exists.", code="file_exists")
        content_changed = data.content is not None and data.content != record.content
        if data.content is not None:
            self._check_size(data.content)
        if new_path is None and not content_changed:
            return record, None

        content = data.content if content_changed else record.content
        values = file_values(new_path or record.path, content, record.size)
        if not content_changed:  # rename only: keep the cached structure
            values.pop("structure")
        analysis: Analysis | None = None
        previous_path = record.path
        details: dict[str, object] = {}
        try:
            self.files.update(record, **values)
            if content_changed:
                details["version"] = self._record_version(record, source)
                analysis = self.analysis.record_file_analysis(record)[0]
            if new_path is not None:
                details["renamed_from"] = previous_path
            if restored_from is not None:
                details["restored_from"] = restored_from
            self.activity.record(
                ActivityType.FILE_RESTORED if restored_from is not None else ActivityType.FILE_UPDATED,
                project,
                file=record,
                analysis=analysis,
                details=details,
            )
            self.project_repository.touch(project)
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{new_path} already exists.", code="file_exists") from None
        if commit:
            self.session.refresh(record)
        return record, analysis

    def delete(self, project_id: uuid.UUID, file_id: uuid.UUID) -> None:
        project = self._writable_project(project_id)
        record = self.get(project_id, file_id)
        self.activity.record(ActivityType.FILE_DELETED, project, file_path=record.path)
        self.files.delete(record)
        self.project_repository.touch(project)
        self.session.commit()

    def list_versions(
        self, project_id: uuid.UUID, file_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[FileVersion], int]:
        return self.versions.list(self.get(project_id, file_id).id, limit=limit, offset=offset)

    def get_version(self, project_id: uuid.UUID, file_id: uuid.UUID, version: int) -> FileVersion:
        record = self.versions.get(self.get(project_id, file_id).id, version)
        if record is None:
            raise NotFoundError(
                "That version does not exist (it may have been pruned).", code="version_not_found"
            )
        return record

    def restore_version(
        self, project_id: uuid.UUID, file_id: uuid.UUID, version: int
    ) -> tuple[ProjectFile, Analysis | None]:
        """Make an earlier version the current content. Recorded as a new version, so it can be undone."""
        content = self.get_version(project_id, file_id, version).content
        return self._update(
            project_id, file_id, FileUpdate(content=content), FileVersionSource.RESTORE, restored_from=version
        )
