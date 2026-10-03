"""Normalized analysis model shared by every analyzer and returned by the API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.services.languages import Language


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"
    SUGGESTION = "suggestion"


class DiagnosticCategory(StrEnum):
    SYNTAX = "syntax"
    LINT = "lint"
    STYLE = "style"
    TYPE = "type"
    SEMANTIC = "semantic"


class Diagnostic(BaseModel):
    """One problem. Lines and columns are 1-based; ``end_column`` is exclusive."""

    id: str
    severity: Severity
    message: str
    source: str = Field(description="Analyzer that produced it, e.g. 'ruff' or 'typescript'.")
    code: str | None = Field(default=None, description="Rule or error code, e.g. 'F401' or 'TS2322'.")
    category: DiagnosticCategory
    file_path: str | None = None
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=1)
    suggestion: str | None = None
    documentation_url: str | None = None
    fixable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityKind(StrEnum):
    SYNTAX = "syntax"
    LINT = "lint"
    TYPES = "types"
    SEMANTIC = "semantic"


class CapabilityStatus(StrEnum):
    PERFORMED = "performed"
    """The check ran on this source."""
    SKIPPED = "skipped"
    """Available, but not run for this source (e.g. linting after a syntax error)."""
    UNAVAILABLE = "unavailable"
    """Supported, but the tool is missing or failed in this environment."""
    NOT_SUPPORTED = "not_supported"
    """CodeWalk does not implement this kind of analysis for the language."""


class Capability(BaseModel):
    kind: CapabilityKind
    status: CapabilityStatus
    analyzer: str | None = None
    detail: str | None = None


class AnalyzerInfo(BaseModel):
    name: str
    version: str | None = None


class AnalysisResult(BaseModel):
    file_path: str | None
    language: Language
    success: bool = Field(description="False when an analyzer failed; diagnostics may then be incomplete.")
    diagnostics: list[Diagnostic]
    capabilities: list[Capability] = Field(
        description="Exactly which kinds of analysis were performed for this language."
    )
    analyzers: list[AnalyzerInfo]
    errors: list[str] = Field(description="Client-safe analyzer failure messages.")
    analysis_duration_ms: float
    analyzed_at: datetime
    analysis_id: str | None = Field(default=None, description="Set when the result was persisted.")
    metadata: dict[str, Any] = Field(default_factory=dict)
