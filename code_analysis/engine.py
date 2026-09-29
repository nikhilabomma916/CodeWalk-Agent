"""Analysis engine: the single entry point the backend should call.

Pipeline (docs/system-architecture.md section 4):
    source -> language resolution -> LanguageAnalyzer -> diagnostics -> AnalysisResult
"""

from __future__ import annotations

from typing import Optional

from code_analysis.analyzers import get_analyzer
from code_analysis.models import AnalysisResult, Diagnostic, Severity
from code_analysis.language_detect import detect_language


class UnsupportedLanguageError(ValueError):
    """Raised when no analyzer is registered for the requested language."""


def analyze_code(
    source: str,
    language: Optional[str] = None,
    file_path: Optional[str] = None,
) -> AnalysisResult:
    """Analyze a single source snippet/file and return an AnalysisResult.

    Args:
        source: raw source text.
        language: language name (e.g. "python"). If omitted, it is
            detected from file_path's extension.
        file_path: optional path/filename, used for language detection
            and included in the result for traceability.

    Raises:
        UnsupportedLanguageError: if the language can't be determined or
            has no registered analyzer.
    """

    resolved_language = language or (detect_language(file_path) if file_path else None)
    if not resolved_language:
        raise UnsupportedLanguageError(
            "Could not determine a language; pass `language` explicitly or a `file_path` with a known extension."
        )

    analyzer = get_analyzer(resolved_language)
    if analyzer is None:
        raise UnsupportedLanguageError(f"No analyzer registered for language '{resolved_language}'.")

    if not source.strip():
        diagnostics: list[Diagnostic] = [
            Diagnostic(
                severity=Severity.WARNING,
                message="Source is empty.",
                line=1,
                column=None,
                source="engine",
                code="EmptySource",
            )
        ]
    else:
        diagnostics = analyzer.analyze(source, file_path)

    return AnalysisResult.from_diagnostics(diagnostics, resolved_language, file_path)
