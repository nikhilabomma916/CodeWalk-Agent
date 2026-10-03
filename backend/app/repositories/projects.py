"""Data access for projects, always scoped to an owner.

Repositories flush but never commit; services own transactions.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Analysis, AnalysisType, Project, ProjectFile


@dataclass
class ProjectStatsRow:
    file_count: int = 0
    total_bytes: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    last_analyzed_at: datetime | None = None


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, owner_id: uuid.UUID, name: str, description: str | None, root_path: str | None
    ) -> Project:
        project = Project(owner_id=owner_id, name=name, description=description, root_path=root_path)
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
        return self.session.scalar(
            select(Project).where(Project.owner_id == owner_id, Project.id == project_id)
        )

    def get_by_name(self, owner_id: uuid.UUID, name: str) -> Project | None:
        return self.session.scalar(
            select(Project).where(Project.owner_id == owner_id, func.lower(Project.name) == name.lower())
        )

    def list(self, owner_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[Project], int]:
        owned = Project.owner_id == owner_id
        total = self.session.scalar(select(func.count()).select_from(Project).where(owned)) or 0
        items = self.session.scalars(
            select(Project)
            .where(owned)
            .order_by(Project.updated_at.desc(), Project.id)
            .limit(limit)
            .offset(offset)
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

    def stats(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ProjectStatsRow]:
        """File counts, sizes, languages, and last project analysis for several projects at once."""
        result = {project_id: ProjectStatsRow() for project_id in project_ids}
        if not project_ids:
            return result
        rows = self.session.execute(
            select(
                ProjectFile.project_id,
                ProjectFile.language,
                func.count(),
                func.coalesce(func.sum(ProjectFile.size), 0),
                func.coalesce(func.sum(ProjectFile.line_count), 0),
            )
            .where(ProjectFile.project_id.in_(project_ids))
            .group_by(ProjectFile.project_id, ProjectFile.language)
        ).all()
        for project_id, language, count, size, lines in rows:
            stats = result[project_id]
            stats.file_count += count
            stats.total_bytes += int(size)
            stats.total_lines += int(lines)
            stats.languages[language] = count
        analyzed = self.session.execute(
            select(Analysis.project_id, func.max(Analysis.created_at))
            .where(
                Analysis.project_id.in_(project_ids),
                Analysis.analysis_type == AnalysisType.PROJECT_INTELLIGENCE,
            )
            .group_by(Analysis.project_id)
        ).all()
        for project_id, created_at in analyzed:
            result[project_id].last_analyzed_at = created_at
        return result
