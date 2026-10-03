"""The activity history: recording events and reading them back.

Services call ``ActivityRecorder`` inside their own transaction, before they
commit, so an event exists exactly when the action it describes was persisted.
Nothing here invents events: the history only contains what was recorded.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import ActivityEvent, ActivityType, Analysis, Project, ProjectFile, User
from app.repositories.activity import ActivityRepository
from app.repositories.analyses import AnalysisRepository, DiagnosticRepository
from app.repositories.files import FileRepository
from app.repositories.projects import ProjectRepository
from app.schemas.history import AnalysisSummary, HistoryEventDetail


class ActivityRecorder:
    def __init__(self, session: Session, user: User) -> None:
        self.user = user
        self.events = ActivityRepository(session)

    def record(
        self,
        event_type: ActivityType,
        project: Project,
        *,
        file: ProjectFile | None = None,
        file_path: str | None = None,
        analysis: Analysis | None = None,
        details: dict[str, Any] | None = None,
        keep_project_link: bool = True,
    ) -> ActivityEvent:
        """Add an event to the current transaction (the caller commits).

        ``keep_project_link=False`` is for deletions: the project row is about to
        disappear, so only its name is kept.
        """
        values: dict[str, Any] = dict(details or {})
        if analysis is not None:
            values.setdefault("diagnostic_count", analysis.diagnostic_count)
            values.setdefault("analysis_status", analysis.status.value)
        return self.events.add(
            user_id=self.user.id,
            event_type=event_type,
            project_id=project.id if keep_project_link else None,
            project_name=project.name,
            file_id=file.id if file is not None and keep_project_link else None,
            file_path=file.path if file is not None else file_path,
            analysis_id=analysis.id if analysis is not None and keep_project_link else None,
            details=values,
        )


class HistoryService:
    """Reads one user's history. Other users' events are reported as not found."""

    def __init__(self, session: Session, user: User) -> None:
        self.session = session
        self.user = user
        self.events = ActivityRepository(session)

    def list(
        self,
        *,
        project_id: uuid.UUID | None,
        event_types: Sequence[ActivityType],
        order: Literal["asc", "desc"],
        limit: int,
        offset: int,
    ) -> tuple[Sequence[ActivityEvent], int]:
        return self.events.list(
            self.user.id,
            project_id=project_id,
            event_types=event_types,
            order=order,
            limit=limit,
            offset=offset,
        )

    def get(self, event_id: uuid.UUID) -> HistoryEventDetail:
        event = self.events.get(self.user.id, event_id)
        if event is None:
            raise NotFoundError("History entry not found.", code="history_event_not_found")

        project = (
            ProjectRepository(self.session).get(self.user.id, event.project_id)
            if event.project_id is not None
            else None
        )
        current_file = (
            FileRepository(self.session).get(project.id, event.file_id)
            if project is not None and event.file_id is not None
            else None
        )
        analysis = (
            AnalysisRepository(self.session).get(event.analysis_id)
            if project is not None and event.analysis_id is not None
            else None
        )
        summary = None
        if analysis is not None and project is not None and analysis.project_id == project.id:
            severities = Counter(
                d.severity.value for d in DiagnosticRepository(self.session).list_by_analysis(analysis.id)
            )
            summary = AnalysisSummary(
                id=analysis.id,
                analysis_type=analysis.analysis_type.value,
                status=analysis.status.value,
                language=analysis.language,
                duration_ms=analysis.duration_ms,
                diagnostic_count=analysis.diagnostic_count,
                severity_counts=dict(severities),
                created_at=analysis.created_at,
            )
        return HistoryEventDetail.build(
            event,
            project_exists=project is not None,
            current_project_name=project.name if project is not None else None,
            current_file_path=current_file.path if current_file is not None else None,
            analysis=summary,
        )
