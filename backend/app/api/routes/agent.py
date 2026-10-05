"""Agent endpoints (Module 11). All require a signed-in user and operate on that user's projects only.

A run reads the project through policy-checked tools and may store proposed changes.
No endpoint applies a change except ``approve``, which re-validates it first.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import AgentActionServiceDep, AgentServiceDep
from app.db.models import AgentActionStatus
from app.schemas.agent import (
    ActionDecisionResponse,
    AgentActionOut,
    AgentEvent,
    AgentRunOut,
    AgentRunRequest,
    AgentStatusResponse,
    GroupDecisionResponse,
    UndoResponse,
)
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse

router = APIRouter(prefix="/agent", tags=["agent"])

_AUTH: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse, "description": "Not signed in."}}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found (or not yours)."}
}


@router.get(
    "/status",
    response_model=AgentStatusResponse,
    summary="Whether the agent can be used, and its tools",
    description="Configuration state only: nothing is sent to the AI provider.",
    responses=_AUTH,
)
def agent_status(service: AgentServiceDep) -> AgentStatusResponse:
    return service.status()


@router.post(
    "/run",
    response_model=AgentRunOut,
    summary="Run the project-aware agent",
    description=(
        "Answers a request about the developer's project by calling read-only tools (search, semantic "
        "retrieval, context, file content, symbols, diagnostics, analysis) and, when asked for a fix, "
        "storing proposed changes for review. Bounded by step, time, context, and proposal limits. "
        "The response contains the answer, progress events, tool-call metadata, and proposed changes. "
        "Provider failures end the run with `status: failed` and an `error`."
    ),
    responses={
        **_AUTH,
        **_NOT_FOUND,
        413: {"model": ErrorResponse, "description": "The open file is too large (`source_too_large`)."},
        422: {
            "model": ErrorResponse,
            "description": "Invalid request (`validation_error`, `invalid_agent_request`).",
        },
        429: {"model": ErrorResponse, "description": "Too many agent requests (`too_many_agent_runs`)."},
        503: {
            "model": ErrorResponse,
            "description": "AI disabled (`ai_disabled`) or not configured (`ai_not_configured`).",
        },
    },
)
def run_agent(request: AgentRunRequest, service: AgentServiceDep) -> AgentRunOut:
    return service.run(request)


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunOut,
    summary="A previous agent run",
    responses={**_AUTH, **_NOT_FOUND},
)
def get_run(run_id: uuid.UUID, service: AgentServiceDep) -> AgentRunOut:
    return service.get_run(run_id)


@router.get(
    "/runs/{run_id}/events",
    response_model=list[AgentEvent],
    summary="Progress events of an agent run",
    responses={**_AUTH, **_NOT_FOUND},
)
def get_run_events(run_id: uuid.UUID, service: AgentServiceDep) -> list[AgentEvent]:
    return service.events(run_id)


_DECISION_ERRORS: dict[int | str, dict[str, Any]] = {
    **_AUTH,
    **_NOT_FOUND,
    409: {
        "model": ErrorResponse,
        "description": "Already decided (`action_not_pending`), the file changed since the proposal "
        "(`stale_action`), or the project is read-only (`project_read_only`).",
    },
}


@router.post(
    "/actions/{action_id}/approve",
    response_model=ActionDecisionResponse,
    summary="Apply a proposed change (explicit developer approval)",
    description=(
        "Re-validates the proposal against the file's current content and applies it only if the file is "
        "unchanged. Saves a new file version, re-runs deterministic analysis, and returns the saved file "
        "and its diagnostics."
    ),
    responses=_DECISION_ERRORS,
)
def approve_action(action_id: uuid.UUID, service: AgentActionServiceDep) -> ActionDecisionResponse:
    return service.approve(action_id)


@router.post(
    "/actions/{action_id}/reject",
    response_model=ActionDecisionResponse,
    summary="Reject a proposed change (no file is changed)",
    responses=_DECISION_ERRORS,
)
def reject_action(action_id: uuid.UUID, service: AgentActionServiceDep) -> ActionDecisionResponse:
    return service.reject(action_id)


@router.post(
    "/groups/{group_id}/approve",
    response_model=GroupDecisionResponse,
    summary="Apply a multi-file proposal (explicit developer approval of every file)",
    description=(
        "Re-validates every file of the proposal against its current content. If any file changed, nothing "
        "is applied and the whole proposal becomes stale. Otherwise all files are saved in one transaction "
        "(new versions, deterministic re-analysis), and their diagnostics counts are returned."
    ),
    responses=_DECISION_ERRORS,
)
def approve_group(group_id: uuid.UUID, service: AgentActionServiceDep) -> GroupDecisionResponse:
    return service.approve_group(group_id)


@router.post(
    "/groups/{group_id}/reject",
    response_model=GroupDecisionResponse,
    summary="Reject a multi-file proposal (no file is changed)",
    responses=_DECISION_ERRORS,
)
def reject_group(group_id: uuid.UUID, service: AgentActionServiceDep) -> GroupDecisionResponse:
    return service.reject_group(group_id)


@router.get(
    "/actions",
    response_model=Page[AgentActionOut],
    summary="AI change history of a project",
    description=(
        "Every change the agent proposed in one of your projects (newest first): what, why, the file, "
        "the diff, and what happened to it (pending, applied, rejected, stale; `result.undone` once "
        "undone)."
    ),
    responses={**_AUTH, **_NOT_FOUND},
)
def list_actions(
    service: AgentActionServiceDep,
    project_id: uuid.UUID,
    status: Annotated[AgentActionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AgentActionOut]:
    items, total = service.list_actions(
        project_id, status=status.value if status else None, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/actions/{action_id}/undo",
    response_model=UndoResponse,
    summary="Undo an applied AI change",
    description=(
        "Only when the file was not changed after the AI change: an edit is reverted by restoring the "
        "previous version (recorded as a new version, so nothing is lost); a file the agent created is "
        "deleted. Otherwise 409 `undo_not_possible` with the reason."
    ),
    responses={**_AUTH, **_NOT_FOUND, 409: {"model": ErrorResponse, "description": "Cannot be undone."}},
)
def undo_action(action_id: uuid.UUID, service: AgentActionServiceDep) -> UndoResponse:
    return service.undo(action_id)
