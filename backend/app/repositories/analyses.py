"""Data access for analyses and their diagnostics."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Analysis, AnalysisType, DiagnosticRecord
from app.services.analysis.models import Diagnostic


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **values: Any) -> Analysis:
        analysis = Analysis(**values)
        self.session.add(analysis)
        self.session.flush()
        return analysis

    def get(self, analysis_id: uuid.UUID) -> Analysis | None:
        return self.session.get(Analysis, analysis_id)

    def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        analysis_type: AnalysisType | None = None,
        file_id: uuid.UUID | None = None,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Analysis], int]:
        conditions = [Analysis.project_id == project_id]
        if analysis_type is not None:
            conditions.append(Analysis.analysis_type == analysis_type)
        if file_id is not None:
            conditions.append(Analysis.file_id == file_id)
        total = self.session.scalar(select(func.count()).select_from(Analysis).where(*conditions)) or 0
        items = self.session.scalars(
            select(Analysis)
            .where(*conditions)
            .order_by(Analysis.created_at.desc(), Analysis.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return items, total

    def latest(self, project_id: uuid.UUID, analysis_type: AnalysisType) -> Analysis | None:
        return self.session.scalar(
            select(Analysis)
            .where(Analysis.project_id == project_id, Analysis.analysis_type == analysis_type)
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )

    def prune_file_history(
        self, file_id: uuid.UUID, keep: int, analysis_type: AnalysisType = AnalysisType.CODE
    ) -> int:
        """Delete all but the newest ``keep`` analyses of one type for a file."""
        same_type = (Analysis.file_id == file_id, Analysis.analysis_type == analysis_type)
        keep_ids = select(Analysis.id).where(*same_type).order_by(Analysis.created_at.desc()).limit(keep)
        result = self.session.execute(delete(Analysis).where(*same_type, Analysis.id.not_in(keep_ids)))
        self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0)


class DiagnosticRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_many(self, analysis_id: uuid.UUID, diagnostics: Iterable[Diagnostic]) -> int:
        records = [
            DiagnosticRecord(
                analysis_id=analysis_id,
                severity=d.severity,
                category=d.category,
                message=d.message,
                source=d.source,
                rule_code=d.code,
                file_path=d.file_path,
                line=d.line,
                column=d.column,
                end_line=d.end_line,
                end_column=d.end_column,
                suggestion=d.suggestion,
                documentation_url=d.documentation_url,
                fixable=d.fixable,
            )
            for d in diagnostics
        ]
        self.session.add_all(records)
        self.session.flush()
        return len(records)

    def list_by_analysis(self, analysis_id: uuid.UUID) -> Sequence[DiagnosticRecord]:
        return self.session.scalars(
            select(DiagnosticRecord)
            .where(DiagnosticRecord.analysis_id == analysis_id)
            .order_by(DiagnosticRecord.line, DiagnosticRecord.column, DiagnosticRecord.id)
        ).all()
