"""Data access for projects. Repositories flush but never commit; services own transactions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, name: str, description: str | None, root_path: str | None) -> Project:
        project = Project(name=name, description=description, root_path=root_path)
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: uuid.UUID) -> Project | None:
        return self.session.get(Project, project_id)

    def get_by_name(self, name: str) -> Project | None:
        return self.session.scalar(select(Project).where(func.lower(Project.name) == name.lower()))

    def list(self, *, limit: int, offset: int) -> tuple[Sequence[Project], int]:
        total = self.session.scalar(select(func.count()).select_from(Project)) or 0
        items = self.session.scalars(
            select(Project).order_by(Project.updated_at.desc(), Project.id).limit(limit).offset(offset)
        ).all()
        return items, total

    def update(self, project: Project, **changes: object) -> Project:
        for key, value in changes.items():
            setattr(project, key, value)
        self.session.flush()
        return project

    def delete(self, project: Project) -> None:
        self.session.delete(project)
        self.session.flush()

    def touch(self, project: Project) -> None:
        """Bump ``updated_at`` (e.g. after its files changed)."""
        project.updated_at = func.now()
        self.session.flush()
