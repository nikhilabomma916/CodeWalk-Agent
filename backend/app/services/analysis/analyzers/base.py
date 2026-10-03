"""Analyzer interface and helpers shared by all analyzers."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.analysis.models import (
    AnalyzerInfo,
    Capability,
    Diagnostic,
    DiagnosticCategory,
    Severity,
)
from app.services.languages import Language

MAX_DIAGNOSTICS = 500


@dataclass(frozen=True)
class AnalysisContext:
    source: str
    language: Language
    file_path: str | None
    timeout_seconds: float


@dataclass
class AnalyzerOutput:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Analyzer(Protocol):
    """A deterministic analyzer for one or more languages.

    Implementations must never execute the analyzed source.
    """

    name: str
    languages: frozenset[Language]

    def info(self) -> list[AnalyzerInfo]: ...

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput: ...


def make_diagnostic(
    *,
    context: AnalysisContext,
    severity: Severity,
    message: str,
    source: str,
    category: DiagnosticCategory,
    line: int,
    column: int,
    end_line: int | None = None,
    end_column: int | None = None,
    code: str | None = None,
    suggestion: str | None = None,
    documentation_url: str | None = None,
    fixable: bool = False,
    metadata: dict[str, Any] | None = None,
) -> Diagnostic:
    line = max(1, line)
    column = max(1, column)
    end_line = max(line, end_line or line)
    end_column = end_column if end_column and (end_line > line or end_column > column) else column + 1
    digest = hashlib.sha1(
        f"{source}|{code}|{line}|{column}|{end_line}|{end_column}|{message}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:16]
    return Diagnostic(
        id=digest,
        severity=severity,
        message=message,
        source=source,
        code=code,
        category=category,
        file_path=context.file_path,
        line=line,
        column=column,
        end_line=end_line,
        end_column=end_column,
        suggestion=suggestion,
        documentation_url=documentation_url,
        fixable=fixable,
        metadata=metadata or {},
    )


class LineIndex:
    """Converts 0-based character offsets into 1-based (line, column) positions."""

    def __init__(self, text: str) -> None:
        self._starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                self._starts.append(index + 1)
        self._length = len(text)

    def position(self, offset: int) -> tuple[int, int]:
        offset = min(max(offset, 0), self._length)
        line = bisect_right(self._starts, offset) - 1
        return line + 1, offset - self._starts[line] + 1
