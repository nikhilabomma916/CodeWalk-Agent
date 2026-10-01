"""Persistence of code analyses.

Decision: real-time editor analysis (POST /analysis/code) is never stored. An
analysis is recorded when file content is saved through the file API, or when a
client explicitly requests analysis of a stored file. Only the newest
``analysis_history_per_file`` analyses are kept per file.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.db.models import Analysis, AnalysisStatus, AnalysisType, DiagnosticRecord, ProjectFile
from app.repositories.analyses import AnalysisRepository, DiagnosticRepository
from app.services.analysis.engine import AnalysisEngine
from app.services.analysis.models import AnalysisResult


class FileNotAnalyzableError(AppError):
    status_code = 422
    code = "file_not_analyzable"


class AnalysisService:
    def __init__(self, session: Session, engine: AnalysisEngine, settings: Settings) -> None:
        self.session = session
        self.engine = engine
        self.settings = settings
        self.analyses = AnalysisRepository(session)
        self.diagnostics = DiagnosticRepository(session)

    def record_file_analysis(self, file: ProjectFile) -> tuple[Analysis, AnalysisResult]:
        """Analyze a stored file and add the records to the session (the caller commits)."""
        if file.content is None:
            raise FileNotAnalyzableError("This file's content is not stored (binary or too large).")
        result = self.engine.analyze(file.content, file_path=file.path)
        analysis = self.analyses.create(
            project_id=file.project_id,
            file_id=file.id,
            analysis_type=AnalysisType.CODE,
            status=AnalysisStatus.COMPLETED if result.success else AnalysisStatus.PARTIAL,
            language=result.language.value,
            content_hash=file.content_hash,
            duration_ms=round(result.analysis_duration_ms),
            diagnostic_count=len(result.diagnostics),
            details={
                "capabilities": [c.model_dump(mode="json") for c in result.capabilities],
                "analyzers": [a.model_dump(mode="json") for a in result.analyzers],
                "errors": result.errors,
                "metadata": result.metadata,
            },
        )
        self.diagnostics.create_many(analysis.id, result.diagnostics)
        self.analyses.prune_file_history(file.id, keep=self.settings.analysis_history_per_file)
        result.analysis_id = str(analysis.id)
        return analysis, result

    def analyze_stored_file(self, file: ProjectFile) -> tuple[Analysis, Sequence[DiagnosticRecord]]:
        """Explicit (manual) analysis of a stored file, committed immediately."""
        analysis, _ = self.record_file_analysis(file)
        self.session.commit()
        return analysis, self.diagnostics.list_by_analysis(analysis.id)

    def get(self, analysis_id: uuid.UUID) -> tuple[Analysis, Sequence[DiagnosticRecord]]:
        analysis = self.analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found.", code="analysis_not_found")
        return analysis, self.diagnostics.list_by_analysis(analysis.id)

    def list(
        self,
        project_id: uuid.UUID,
        *,
        analysis_type: AnalysisType | None,
        file_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Analysis], int]:
        return self.analyses.list_by_project(
            project_id, analysis_type=analysis_type, file_id=file_id, limit=limit, offset=offset
        )
