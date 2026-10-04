"""The analysis engine: selects analyzers for a language and normalizes their output."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.core.exceptions import AppError
from app.core.metrics import timed
from app.services.analysis.analyzers.base import MAX_DIAGNOSTICS, AnalysisContext, AnalyzerOutput
from app.services.analysis.analyzers.html_analyzer import HtmlAnalyzer
from app.services.analysis.analyzers.json_analyzer import JsonAnalyzer
from app.services.analysis.analyzers.markdown_analyzer import MarkdownAnalyzer
from app.services.analysis.analyzers.python_analyzer import PythonAnalyzer
from app.services.analysis.analyzers.sql_analyzer import SqlAnalyzer
from app.services.analysis.analyzers.treesitter_syntax import TreeSitterSyntaxAnalyzer
from app.services.analysis.analyzers.typescript_analyzer import TypeScriptAnalyzer
from app.services.analysis.models import (
    AnalysisResult,
    AnalyzerInfo,
    Capability,
    CapabilityKind,
    CapabilityStatus,
)
from app.services.analysis.registry import AnalyzerRegistry
from app.services.analysis.typescript_worker import TypeScriptWorker
from app.services.languages import Language, detect_language

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"error": 0, "warning": 1, "information": 2, "suggestion": 3}


class SourceTooLargeError(AppError):
    status_code = 413
    code = "source_too_large"


class AnalysisEngine:
    def __init__(self, registry: AnalyzerRegistry, *, max_source_bytes: int, timeout_seconds: float) -> None:
        self.registry = registry
        self.max_source_bytes = max_source_bytes
        self.timeout_seconds = timeout_seconds

    @classmethod
    def create_default(
        cls,
        *,
        max_source_bytes: int,
        timeout_seconds: float,
        typescript_worker: TypeScriptWorker,
    ) -> AnalysisEngine:
        registry = AnalyzerRegistry(
            [
                PythonAnalyzer(),
                TypeScriptAnalyzer(typescript_worker),
                JsonAnalyzer(),
                HtmlAnalyzer(),
                TreeSitterSyntaxAnalyzer(),
                SqlAnalyzer(),
                MarkdownAnalyzer(),
            ]
        )
        return cls(registry, max_source_bytes=max_source_bytes, timeout_seconds=timeout_seconds)

    def resolve_language(self, language: Language | None, file_path: str | None) -> Language:
        if language is not None and language is not Language.UNKNOWN:
            return language
        return detect_language(file_path) if file_path else Language.UNKNOWN

    def analyze(
        self, source: str, *, language: Language | None = None, file_path: str | None = None
    ) -> AnalysisResult:
        """Run every analyzer registered for the language. Never executes the source."""
        with timed("code_analysis") as metric:
            result = self._analyze(source, language=language, file_path=file_path)
            metric["outcome"] = "ok" if result.success else "partial"
            return result

    def _analyze(
        self, source: str, *, language: Language | None = None, file_path: str | None = None
    ) -> AnalysisResult:
        size = len(source.encode("utf-8"))
        if size > self.max_source_bytes:
            raise SourceTooLargeError(
                f"Source is {size} bytes; the analysis limit is {self.max_source_bytes} bytes."
            )
        resolved = self.resolve_language(language, file_path)
        started = time.perf_counter()
        context = AnalysisContext(
            source=source, language=resolved, file_path=file_path, timeout_seconds=self.timeout_seconds
        )

        analyzers = self.registry.for_language(resolved)
        combined = AnalyzerOutput()
        infos: list[AnalyzerInfo] = []
        if not analyzers:
            combined.capabilities = [
                Capability(
                    kind=kind,
                    status=CapabilityStatus.NOT_SUPPORTED,
                    detail=f"No analyzer is available for {resolved.value}",
                )
                for kind in (CapabilityKind.SYNTAX, CapabilityKind.LINT)
            ]
        for analyzer in analyzers:
            try:
                output = analyzer.analyze(context)
            except Exception:
                logger.exception("Analyzer %s crashed (language=%s)", analyzer.name, resolved.value)
                output = AnalyzerOutput(errors=[f"The {analyzer.name} analyzer failed on this input"])
            combined.diagnostics.extend(output.diagnostics)
            combined.capabilities.extend(output.capabilities)
            combined.errors.extend(output.errors)
            infos.extend(analyzer.info())

        diagnostics = sorted(
            combined.diagnostics,
            key=lambda d: (d.line, d.column, _SEVERITY_ORDER[d.severity.value], d.source),
        )
        truncated = len(diagnostics) > MAX_DIAGNOSTICS
        return AnalysisResult(
            file_path=file_path,
            language=resolved,
            success=not combined.errors,
            diagnostics=diagnostics[:MAX_DIAGNOSTICS],
            capabilities=combined.capabilities,
            analyzers=infos,
            errors=combined.errors,
            analysis_duration_ms=round((time.perf_counter() - started) * 1000, 2),
            analyzed_at=datetime.now(UTC),
            metadata={"source_bytes": size, "truncated": truncated, "total_diagnostics": len(diagnostics)},
        )
