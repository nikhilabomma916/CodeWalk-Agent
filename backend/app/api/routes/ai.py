"""AI assistance endpoints (Modules 7 and 8). All require a signed-in user.

Answers are advisory and validated before they are returned. A fix suggestion
is a proposal only: no endpoint here modifies a file.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AIAssistantDep, AIServiceDep, CurrentUserDep
from app.schemas.ai import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIExplainRequest,
    AIExplanationResponse,
    AIFixRequest,
    AIFixSuggestionResponse,
    AIStatusResponse,
)
from app.schemas.errors import ErrorResponse

router = APIRouter(prefix="/ai", tags=["ai"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Not signed in."},
    404: {"model": ErrorResponse, "description": "Project or file not found (or not yours)."},
    413: {"model": ErrorResponse, "description": "Code or context too large."},
    422: {
        "model": ErrorResponse,
        "description": "Invalid request or range (`invalid_range`), or the provider declined (`ai_refused`).",
    },
    429: {
        "model": ErrorResponse,
        "description": "Too many AI requests (`too_many_ai_requests`) or provider rate limit "
        "(`ai_rate_limited`).",
    },
    502: {
        "model": ErrorResponse,
        "description": "Provider error or unusable answer (`ai_provider_error`, `ai_malformed_response`).",
    },
    503: {
        "model": ErrorResponse,
        "description": "AI disabled (`ai_disabled`), not configured (`ai_not_configured`), or provider "
        "unreachable (`ai_unavailable`).",
    },
    504: {"model": ErrorResponse, "description": "Provider timeout (`ai_timeout`)."},
}


@router.get(
    "/status",
    response_model=AIStatusResponse,
    summary="Whether AI assistance can be used",
    description="Configuration state only: nothing is sent to the provider and no credential is returned.",
    responses={401: _ERRORS[401]},
)
def ai_status(service: AIServiceDep, _: CurrentUserDep) -> AIStatusResponse:
    return service.status()


@router.post(
    "/analyze",
    response_model=AIAnalysisResponse,
    summary="AI code review",
    description=(
        "Reviews the submitted code together with its deterministic diagnostics for likely bugs, logic, "
        "maintainability, complexity, duplication, performance, and evidence-backed security concerns. "
        "With `project_id`, related project code is added as context and the result is recorded."
    ),
    responses=_ERRORS,
)
def ai_analyze(request: AIAnalysisRequest, assistant: AIAssistantDep) -> AIAnalysisResponse:
    return assistant.analyze(request)


@router.post(
    "/explain",
    response_model=AIExplanationResponse,
    summary="Explain a diagnostic",
    description="Explains one deterministic diagnostic: meaning, likely cause, impact, and how to fix it.",
    responses=_ERRORS,
)
def ai_explain(request: AIExplainRequest, assistant: AIAssistantDep) -> AIExplanationResponse:
    return assistant.explain(request)


@router.post(
    "/fix-suggestion",
    response_model=AIFixSuggestionResponse,
    summary="Propose a fix (never applied by the server)",
    description=(
        "Returns validated edits, the resulting code, and a unified diff, computed against the submitted "
        "code. The client shows them for review; the developer decides whether to apply them."
    ),
    responses=_ERRORS,
)
def ai_fix_suggestion(request: AIFixRequest, assistant: AIAssistantDep) -> AIFixSuggestionResponse:
    return assistant.fix_suggestion(request)
