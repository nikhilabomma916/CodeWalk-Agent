"""Request/response models for the AI endpoints (Modules 7 and 8).

AI output is advisory: every answer carries the provider, model, a categorical
confidence (``low``/``medium``/``high`` as stated by the model, never an
invented percentage), and warnings about anything that was dropped or limited.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import ProjectFilePath
from app.services.analysis.models import DiagnosticCategory, Severity
from app.services.languages import Language

MAX_DIAGNOSTICS = 200
MAX_LINE = 1_000_000


class AIAnalysisType(StrEnum):
    GENERAL_REVIEW = "general_review"
    BUG_DETECTION = "bug_detection"
    QUALITY_REVIEW = "quality_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_REVIEW = "performance_review"
    EXPLAIN_CODE = "explain_code"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FindingCategory(StrEnum):
    BUG = "bug"
    LOGIC = "logic"
    MAINTAINABILITY = "maintainability"
    CODE_SMELL = "code_smell"
    COMPLEXITY = "complexity"
    DUPLICATION = "duplication"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    PERFORMANCE = "performance"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    EXPLANATION = "explanation"


class Basis(StrEnum):
    OBSERVED = "observed"  # directly visible in the supplied code
    INFERRED = "inferred"  # a judgment about likely behavior


class SourceRange(BaseModel):
    """1-based, inclusive start; end column exclusive (same as diagnostics)."""

    model_config = ConfigDict(extra="forbid")

    start_line: int = Field(ge=1, le=MAX_LINE)
    start_column: int = Field(default=1, ge=1, le=100_000)
    end_line: int = Field(ge=1, le=MAX_LINE)
    end_column: int = Field(default=1, ge=1, le=100_000)

    @model_validator(mode="after")
    def _ordered(self) -> SourceRange:
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise ValueError("range end is before its start")
        return self


class DiagnosticInput(BaseModel):
    """A deterministic diagnostic as produced by POST /analysis/code."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=200)
    severity: Severity
    message: str = Field(min_length=1, max_length=2000)
    source: str = Field(max_length=64)
    code: str | None = Field(default=None, max_length=64)
    category: DiagnosticCategory = DiagnosticCategory.SEMANTIC
    line: int = Field(ge=1, le=MAX_LINE)
    column: int = Field(ge=1, le=100_000)
    end_line: int = Field(ge=1, le=MAX_LINE)
    end_column: int = Field(ge=1, le=100_000)


class AIRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Current content of the file (the editor buffer; may be unsaved).")
    language: Language | None = Field(default=None, description="Detected from file_path when omitted.")
    file_path: ProjectFilePath
    project_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "When set, the server checks that the caller owns the project, adds related project "
            "context (imports, importers, matching symbols), and records the result in the history."
        ),
    )
    diagnostics: list[DiagnosticInput] = Field(default_factory=list, max_length=MAX_DIAGNOSTICS)


class AIAnalysisRequest(AIRequestBase):
    analysis_type: AIAnalysisType = AIAnalysisType.GENERAL_REVIEW
    selected_range: SourceRange | None = Field(default=None, description="Focus the review on these lines.")


class AIExplainRequest(AIRequestBase):
    diagnostic: DiagnosticInput


class AIFixRequest(AIRequestBase):
    diagnostic: DiagnosticInput | None = Field(
        default=None, description="The problem to fix. Without it, `instruction` must say what to change."
    )
    instruction: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _has_target(self) -> AIFixRequest:
        if self.diagnostic is None and not (self.instruction and self.instruction.strip()):
            raise ValueError("either diagnostic or instruction is required")
        return self


class AIFinding(BaseModel):
    id: str
    severity: FindingSeverity
    category: FindingCategory
    title: str
    description: str
    reasoning: str
    basis: Basis = Field(description="observed (visible in the code) or inferred (a judgment).")
    file_path: str
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None
    confidence: Confidence
    suggestion: str | None
    related_diagnostic_id: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSummary(BaseModel):
    """What project context was sent to the provider (paths and symbols only)."""

    used: bool
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    snippet_count: int = 0
    semantic_snippet_count: int = Field(
        default=0, description="Snippets found by semantic retrieval (Module 10)."
    )
    truncated: bool = False


class AIResponseBase(BaseModel):
    request_id: str = Field(description="CodeWalk request id (matches the X-Request-ID header).")
    provider: str
    model: str
    generated_at: datetime
    confidence: Confidence
    warnings: list[str]
    context: ContextSummary
    record_id: uuid.UUID | None = Field(description="Stored analysis record, when a project was given.")


class AIAnalysisResponse(AIResponseBase):
    analysis_type: AIAnalysisType
    summary: str
    findings: list[AIFinding]


class RelatedLocation(BaseModel):
    file_path: str
    line: int | None
    reason: str


class AIExplanationResponse(AIResponseBase):
    diagnostic_id: str
    problem: str = Field(description="The diagnostic message being explained.")
    explanation: str
    cause: str
    impact: str
    suggested_fix: str
    related_code_locations: list[RelatedLocation]


class CodeEdit(BaseModel):
    """One replacement in a single file. Positions are 1-based; end column is exclusive."""

    model_config = ConfigDict(extra="forbid")

    file_path: ProjectFilePath
    start_line: int = Field(ge=1, le=MAX_LINE)
    start_column: int = Field(ge=1, le=100_000)
    end_line: int = Field(ge=1, le=MAX_LINE)
    end_column: int = Field(ge=1, le=100_000)
    replacement_text: str = Field(max_length=200_000)


class AIFixSuggestionResponse(AIResponseBase):
    status: str = Field(description="`suggested`, or `no_suggestion` when the model proposed no safe change.")
    summary: str
    explanation: str
    file_path: str
    original_code: str = Field(description="The code the suggestion was computed against.")
    original_hash: str = Field(
        description="SHA-256 of original_code; apply only if the buffer still matches."
    )
    suggested_code: str
    diff: str = Field(description="Unified diff from original_code to suggested_code.")
    edits: list[CodeEdit]


class AIStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    available: bool = Field(description="enabled and configured: AI requests can be attempted.")
    provider: str | None
    model: str | None
    detail: str | None = Field(description="Why AI is unavailable, when it is.")
    analysis_types: list[AIAnalysisType]


MAX_COMPLETION_PREFIX_CHARS = 20_000
MAX_COMPLETION_SUFFIX_CHARS = 8_000


class AICompletionRequest(BaseModel):
    """The text around the cursor for inline completion (ghost text). Nothing is stored."""

    model_config = ConfigDict(extra="forbid")

    file_path: ProjectFilePath
    language: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9+#._-]+$")
    prefix: str = Field(max_length=MAX_COMPLETION_PREFIX_CHARS, description="Code before the cursor.")
    suffix: str = Field(default="", max_length=MAX_COMPLETION_SUFFIX_CHARS, description="Code after it.")
    mode: Literal["auto", "comment"] = Field(
        default="auto", description='"comment": the line before the cursor is a comment asking for code.'
    )


class AICompletionResponse(BaseModel):
    completion: str = Field(description="Text to insert at the cursor; empty when nothing fits.")
    provider: str
    model: str | None
