"""Diagnostic and result schemas for the Code Analysis Engine.

These are Pydantic models so the backend team can import them directly
into FastAPI request/response schemas without redefining the shape.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Diagnostic classification, per docs/PRD.md section 13."""

    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class Diagnostic(BaseModel):
    """A single detected issue in source code."""

    severity: Severity
    message: str
    line: int = Field(ge=1, description="1-indexed line number")
    column: Optional[int] = Field(default=None, ge=0, description="0-indexed column offset")
    source: str = Field(description="Tool that produced the diagnostic, e.g. 'syntax', 'pyflakes'")
    code: Optional[str] = Field(default=None, description="Rule/error code where available")


class AnalysisRequest(BaseModel):
    """Input to the analysis engine."""

    source: str
    language: str
    file_path: Optional[str] = None


class AnalysisResult(BaseModel):
    """Output of the analysis engine for a single file/snippet."""

    file_path: Optional[str] = None
    language: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    suggestion_count: int = 0

    @classmethod
    def from_diagnostics(
        cls, diagnostics: list[Diagnostic], language: str, file_path: Optional[str] = None
    ) -> "AnalysisResult":
        return cls(
            file_path=file_path,
            language=language,
            diagnostics=diagnostics,
            error_count=sum(1 for d in diagnostics if d.severity == Severity.ERROR),
            warning_count=sum(1 for d in diagnostics if d.severity == Severity.WARNING),
            suggestion_count=sum(1 for d in diagnostics if d.severity == Severity.SUGGESTION),
        )
