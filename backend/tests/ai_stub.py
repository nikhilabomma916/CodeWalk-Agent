"""A controlled AIProvider for tests.

It returns queued answers (or raises queued errors) and records each request,
so tests can check CodeWalk's own behavior: prompts, context, validation,
normalization, persistence, authorization. It says nothing about whether a real
provider works; that is covered by the provider tests (mock transport) and the
optional live smoke test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.ai.base import AIError, ProviderStatus, StructuredRequest, StructuredResult


@dataclass
class StubProvider:
    name: str = "stub"
    model: str = "stub-model"
    configured: bool = True
    answers: list[dict[str, Any] | AIError] = field(default_factory=list)
    requests: list[StructuredRequest] = field(default_factory=list)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.name,
            model=self.model,
            configured=self.configured,
            detail=None if self.configured else "stub not configured",
        )

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        self.requests.append(request)
        if not self.answers:
            raise AssertionError("StubProvider received an unexpected request")
        answer = self.answers.pop(0)
        if isinstance(answer, AIError):
            raise answer
        return StructuredResult(
            data=answer, model=self.model, request_id="stub-req", usage={"input_tokens": 1}
        )


def finding(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "severity": "warning",
        "category": "bug",
        "title": "Iterates over the wrong name",
        "description": "The generator iterates over `item` instead of `items`.",
        "reasoning": "`item` is the loop variable; the parameter is `items`.",
        "basis": "observed",
        "evidence": "for item in item",
        "line": 2,
        "end_line": 2,
        "confidence": "high",
        "suggestion": "Iterate over `items`.",
        "related_diagnostic_id": None,
    }
    values.update(overrides)
    return values


def analysis(*findings: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "summary": "One likely bug.",
        "findings": list(findings),
        "confidence": "medium",
        "warnings": [],
    }
    values.update(overrides)
    return values


def explanation(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "explanation": "`total` is used before it is defined.",
        "cause": "The accumulator is never initialised.",
        "impact": "The function raises NameError when called.",
        "suggested_fix": "Initialise `total = 0` before the loop.",
        "related_locations": [],
        "confidence": "high",
        "warnings": [],
    }
    values.update(overrides)
    return values


def fix(*edits: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "summary": "Initialise the accumulator.",
        "explanation": "Adds `total = 0` before the loop.",
        "edits": list(edits),
        "no_change_reason": None,
        "confidence": "high",
        "warnings": [],
    }
    values.update(overrides)
    return values
