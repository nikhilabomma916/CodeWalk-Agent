"""File business rules. File content is user data: stored and analyzed, never executed."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import Analysis, Project, ProjectFile
from app.repositories.files import FileRepository
from app.repositories.projects import ProjectRepository
from app.schemas.projects import FileCreate, FileUpdate
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
    def __init__(self, session: Session, settings: Settings, analysis: AnalysisService) -> None:
        self.session = session
        self.settings = settings
        self.analysis = analysis
        self.projects = ProjectService(session, settings)
        self.project_repository = ProjectRepository(session)
        self.files = FileRepository(session)

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

    def get(self, project_id: uuid.UUID, file_id: uuid.UUID) -> ProjectFile:
        self.projects.get(project_id)
        record = self.files.get(project_id, file_id)
        if record is None:
            raise NotFoundError("File not found.", code="file_not_found")
        return record

    def list(self, project_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[ProjectFile], int]:
        self.projects.get(project_id)
        return self.files.list_metadata(project_id, limit=limit, offset=offset)

    def create(self, project_id: uuid.UUID, data: FileCreate) -> tuple[ProjectFile, Analysis | None]:
        project = self._writable_project(project_id)
        self._check_size(data.content)
        if self.files.get_by_path(project_id, data.path) is not None:
            raise ConflictError(f"{data.path} already exists.", code="file_exists")
        try:
            record = self.files.create(project_id=project_id, **file_values(data.path, data.content))
            analysis = self.analysis.record_file_analysis(record)[0] if data.content else None
            self.project_repository.touch(project)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{data.path} already exists.", code="file_exists") from None
        return record, analysis

    def update(
        self, project_id: uuid.UUID, file_id: uuid.UUID, data: FileUpdate
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
        try:
            self.files.update(record, **values)
            if content_changed:
                analysis = self.analysis.record_file_analysis(record)[0]
            self.project_repository.touch(project)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{new_path} already exists.", code="file_exists") from None
        self.session.refresh(record)
        return record, analysis

    def delete(self, project_id: uuid.UUID, file_id: uuid.UUID) -> None:
        project = self._writable_project(project_id)
        self.files.delete(self.get(project_id, file_id))
        self.project_repository.touch(project)
        self.session.commit()
