"""The JSON shapes the model must answer with.

Each model is used twice: its JSON schema constrains the provider's output
(structured outputs), and it validates whatever comes back before anything is
returned to clients. Every field is required (nullable where optional) and no
numeric/length constraints are declared, so the schemas stay within what
structured outputs accept; bounds are enforced afterwards in normalization.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ConfidenceLabel = Literal["low", "medium", "high"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelFinding(_Strict):
    severity: Literal["error", "warning", "info"]
    category: Literal[
        "bug",
        "logic",
        "maintainability",
        "code_smell",
        "complexity",
        "duplication",
        "suspicious_pattern",
        "performance",
        "security",
        "architecture",
        "explanation",
    ]
    title: str
    description: str
    reasoning: str
    basis: Literal["observed", "inferred"]
    evidence: str
    line: int | None
    end_line: int | None
    confidence: ConfidenceLabel
    suggestion: str | None
    related_diagnostic_id: str | None


class ModelAnalysis(_Strict):
    summary: str
    findings: list[ModelFinding]
    confidence: ConfidenceLabel
    warnings: list[str]


class ModelLocation(_Strict):
    file_path: str
    line: int | None
    reason: str


class ModelExplanation(_Strict):
    explanation: str
    cause: str
    impact: str
    suggested_fix: str
    related_locations: list[ModelLocation]
    confidence: ConfidenceLabel
    warnings: list[str]


class ModelLineEdit(_Strict):
    start_line: int
    end_line: int
    replacement: str


class ModelFix(_Strict):
    summary: str
    explanation: str
    edits: list[ModelLineEdit]
    no_change_reason: str | None
    confidence: ConfidenceLabel
    warnings: list[str]


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()
