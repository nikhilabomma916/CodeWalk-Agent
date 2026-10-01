from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AnalysisStatus, AnalysisType
from app.schemas.common import RelativePath
from app.services.analysis.models import DiagnosticCategory, Severity
from app.services.languages import Language


class AnalyzeCodeRequest(BaseModel):
    """Real-time analysis of editor content. Nothing is stored and the code is never executed."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Source text to analyze.")
    language: Language | None = Field(
        default=None, description="Overrides detection from file_path; omit to detect from the extension."
    )
    file_path: RelativePath | None = Field(
        default=None, description="Project-relative label used for language detection and messages only."
    )


class LanguageSupport(BaseModel):
    language: Language
    analyzers: list[str]
    available: bool
    detail: str | None = None


class StoredDiagnostic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    severity: Severity
    category: DiagnosticCategory
    message: str
    source: str
    rule_code: str | None
    file_path: str | None
    line: int
    column: int
    end_line: int
    end_column: int
    suggestion: str | None
    documentation_url: str | None
    fixable: bool


class AnalysisRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    file_id: uuid.UUID | None
    analysis_type: AnalysisType
    status: AnalysisStatus
    language: str | None
    content_hash: str | None
    duration_ms: int
    diagnostic_count: int
    details: dict[str, Any]
    created_at: datetime


class AnalysisRecordDetail(AnalysisRecord):
    diagnostics: list[StoredDiagnostic]

    @classmethod
    def build(cls, analysis: object, diagnostics: Sequence[object]) -> AnalysisRecordDetail:
        return cls.model_validate(
            {
                **AnalysisRecord.model_validate(analysis).model_dump(),
                "diagnostics": [StoredDiagnostic.model_validate(d) for d in diagnostics],
            }
        )
