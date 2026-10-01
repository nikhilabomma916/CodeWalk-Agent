"""Project intelligence over stored projects.

Pipeline: (linked folder → secure scan → sync file records) → per-file structure
(cached in ``files.structure`` by content hash) → relationships and statistics →
an ``analyses`` record of type ``project_intelligence``.

Rescanning a linked folder updates changed files, creates new ones, and deletes
records for files that disappeared; unchanged files are left untouched.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.db.models import AnalysisStatus, AnalysisType, Project, ProjectFile
from app.repositories.analyses import AnalysisRepository
from app.repositories.files import FileRepository
from app.services.file_content import file_values
from app.services.languages import Language
from app.services.project_intelligence.models import (
    STRUCTURE_VERSION,
    FileStructure,
    ProjectAnalysisResult,
    ProjectSummary,
    SourceFile,
    SyncSummary,
)
from app.services.project_intelligence.project_analyzer import analyze_project, extract_structure
from app.services.project_intelligence.scanner import ScanOptions, ScanResult, scan_directory
from app.services.projects import ProjectService

MAX_STORED_ERRORS = 200


class ProjectIntelligenceService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectService(session, settings)
        self.files = FileRepository(session)
        self.analyses = AnalysisRepository(session)

    def analyze(self, project_id: uuid.UUID) -> ProjectAnalysisResult:
        started = time.perf_counter()
        project = self.projects.get(project_id)
        sync: SyncSummary | None = None
        directories: list[str] | None = None
        skipped = 0
        if project.root_path is not None:
            folder = self.projects.resolve_root(project.root_path)
            scan = scan_directory(
                folder,
                ScanOptions(
                    max_files=self.settings.scan_max_files, max_file_bytes=self.settings.max_source_bytes
                ),
                gitignore_boundary=self.settings.workspace_root,
            )
            sync = self._sync(project, scan)
            directories = scan.directories
            skipped = len(scan.skipped)

        result = self._build(project, self.files.list_all(project.id), directories, skipped)
        result.sync = sync
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        analysis = self.analyses.create(
            project_id=project.id,
            analysis_type=AnalysisType.PROJECT_INTELLIGENCE,
            status=AnalysisStatus.PARTIAL if result.errors else AnalysisStatus.COMPLETED,
            duration_ms=round(result.duration_ms),
            diagnostic_count=0,
            details=self._details(result, directories, skipped),
        )
        self.projects.projects.touch(project)
        self.session.commit()
        result.analysis_id = str(analysis.id)
        result.analyzed_at = analysis.created_at.astimezone(UTC)
        return result

    def latest(self, project_id: uuid.UUID) -> ProjectAnalysisResult:
        """The current intelligence view, built from stored files without rescanning."""
        project = self.projects.get(project_id)
        analysis = self.analyses.latest(project.id, AnalysisType.PROJECT_INTELLIGENCE)
        if analysis is None:
            raise NotFoundError("This project has not been analyzed yet.", code="not_analyzed")
        directories = analysis.details.get("directories") if project.root_path else None
        skipped = int(analysis.details.get("skipped_files", 0))
        result = self._build(project, self.files.list_all(project.id), directories, skipped)
        self.session.commit()  # persist structures computed for files changed since the last analysis
        result.analysis_id = str(analysis.id)
        result.analyzed_at = analysis.created_at.astimezone(UTC)
        return result

    def _build(
        self,
        project: Project,
        records: Sequence[ProjectFile],
        directories: list[str] | None,
        skipped: int,
    ) -> ProjectAnalysisResult:
        by_path = {record.path: record for record in records}

        def cached_structure(file: SourceFile, language: Language) -> FileStructure:
            record = by_path[file.path]
            cached = record.structure
            if (
                cached is not None
                and cached.get("version") == STRUCTURE_VERSION
                and cached.get("content_hash") == record.content_hash
            ):
                return FileStructure.model_validate(cached["data"])
            structure = extract_structure(file, language)
            record.structure = {
                "version": STRUCTURE_VERSION,
                "content_hash": record.content_hash,
                "data": structure.model_dump(mode="json"),
            }
            return structure

        files = [
            SourceFile(
                path=record.path,
                size=record.size,
                content=record.content,
                skipped_reason=None if record.content is not None else "binary or too large",
            )
            for record in records
        ]
        return analyze_project(
            project=ProjectSummary(id=str(project.id), name=project.name, root_path=project.root_path),
            files=files,
            directories=directories,
            skipped_count=skipped,
            structure_provider=cached_structure,
        )

    def _sync(self, project: Project, scan: ScanResult) -> SyncSummary:
        existing = {record.path: record for record in self.files.list_all(project.id)}
        created = updated = unchanged = 0
        seen: set[str] = set()
        for file in scan.files:
            seen.add(file.path)
            values = file_values(file.path, file.content, file.size)
            record = existing.get(file.path)
            if record is None:
                self.files.create(project_id=project.id, **values)
                created += 1
            elif record.content_hash != values["content_hash"] or record.size != values["size"]:
                self.files.update(record, **values)
                updated += 1
            else:
                unchanged += 1
        removed = [path for path in existing if path not in seen]
        self.files.delete_paths(project.id, removed)
        return SyncSummary(created=created, updated=updated, deleted=len(removed), unchanged=unchanged)

    @staticmethod
    def _details(
        result: ProjectAnalysisResult, directories: list[str] | None, skipped: int
    ) -> dict[str, Any]:
        return {
            "statistics": result.statistics.model_dump(mode="json"),
            "errors": [error.model_dump(mode="json") for error in result.errors[:MAX_STORED_ERRORS]],
            "sync": result.sync.model_dump(mode="json") if result.sync else None,
            "directories": directories,
            "skipped_files": skipped,
        }
