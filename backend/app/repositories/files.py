"""Data access for project files."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, defer

from app.db.models import ProjectFile


class FileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, project_id: uuid.UUID, **values: Any) -> ProjectFile:
        record = ProjectFile(project_id=project_id, **values)
        self.session.add(record)
        self.session.flush()
        return record

    def get(self, project_id: uuid.UUID, file_id: uuid.UUID) -> ProjectFile | None:
        return self.session.scalar(
            select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == file_id)
        )

    def get_by_path(self, project_id: uuid.UUID, path: str) -> ProjectFile | None:
        return self.session.scalar(
            select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.path == path)
        )

    def list_metadata(
        self, project_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[ProjectFile], int]:
        """Files without their (potentially large) content and structure columns."""
        total = (
            self.session.scalar(
                select(func.count()).select_from(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            or 0
        )
        items = self.session.scalars(
            select(ProjectFile)
            .options(defer(ProjectFile.content), defer(ProjectFile.structure))
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.path)
            .limit(limit)
            .offset(offset)
        ).all()
        return items, total

    def list_all(self, project_id: uuid.UUID) -> Sequence[ProjectFile]:
        """Every file with content; used by project scanning and intelligence."""
        return self.session.scalars(
            select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.path)
        ).all()

    def update(self, record: ProjectFile, **changes: Any) -> ProjectFile:
        for key, value in changes.items():
            setattr(record, key, value)
        self.session.flush()
        return record

    def delete(self, record: ProjectFile) -> None:
        self.session.delete(record)
        self.session.flush()

    def delete_paths(self, project_id: uuid.UUID, paths: Sequence[str]) -> int:
        if not paths:
            return 0
        result = self.session.execute(
            delete(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.path.in_(paths))
        )
        self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0)
