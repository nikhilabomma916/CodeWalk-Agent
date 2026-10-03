from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ActivityEvent, ActivityType


class HistoryEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: ActivityType
    project_id: uuid.UUID | None = Field(description="None once the project was deleted.")
    project_name: str = Field(description="The project's name when the event happened.")
    file_id: uuid.UUID | None = Field(description="None for project events, or once the file was deleted.")
    file_path: str | None = Field(description="The file's path when the event happened.")
    analysis_id: uuid.UUID | None = Field(description="None when no analysis ran, or once it was pruned.")
    details: dict[str, Any] = Field(
        description=(
            "Event-specific summary, e.g. `diagnostic_count`, `analysis_status`, `version`, "
            "`changed` (project fields), `renamed_from`, `statistics` (project analysis)."
        )
    )
    created_at: datetime


class AnalysisSummary(BaseModel):
    id: uuid.UUID
    analysis_type: str
    status: str
    language: str | None
    duration_ms: int
    diagnostic_count: int
    severity_counts: dict[str, int] = Field(description="Diagnostics per severity (error, warning, ...).")
    created_at: datetime


class HistoryEventDetail(HistoryEvent):
    project_exists: bool = Field(description="Whether the project still exists.")
    current_project_name: str | None = Field(description="The project's name now, if it still exists.")
    current_file_path: str | None = Field(
        description="Where the file is now (it may have been renamed), if it still exists."
    )
    analysis: AnalysisSummary | None = Field(description="The analysis recorded with the event, if kept.")

    @classmethod
    def build(
        cls,
        event: ActivityEvent,
        *,
        project_exists: bool,
        current_project_name: str | None,
        current_file_path: str | None,
        analysis: AnalysisSummary | None,
    ) -> HistoryEventDetail:
        return cls.model_validate(
            {
                **HistoryEvent.model_validate(event).model_dump(),
                "project_exists": project_exists,
                "current_project_name": current_project_name,
                "current_file_path": current_file_path,
                "analysis": analysis,
            }
        )
