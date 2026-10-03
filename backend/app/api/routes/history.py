from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import HistoryServiceDep
from app.db.models import ActivityType
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse
from app.schemas.history import HistoryEvent, HistoryEventDetail

router = APIRouter(
    prefix="/history",
    tags=["history"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        503: {"model": ErrorResponse, "description": "Database not configured or unavailable."},
    },
)


@router.get(
    "",
    response_model=Page[HistoryEvent],
    summary="The signed-in user's activity",
    description=(
        "Events recorded when projects and files were created, changed, deleted, or analyzed. "
        "Only the caller's own events are returned. Repeat `event_type` to filter on several types."
    ),
)
def list_history(
    service: HistoryServiceDep,
    project_id: uuid.UUID | None = None,
    event_type: Annotated[list[ActivityType] | None, Query()] = None,
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[HistoryEvent]:
    items, total = service.list(
        project_id=project_id, event_types=event_type or [], order=order, limit=limit, offset=offset
    )
    return Page(
        items=[HistoryEvent.model_validate(event) for event in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{event_id}",
    response_model=HistoryEventDetail,
    summary="One history entry with its context",
    description="Adds the current project/file location and the recorded analysis summary, if still present.",
    responses={404: {"model": ErrorResponse, "description": "No such entry for this user."}},
)
def get_history_event(event_id: uuid.UUID, service: HistoryServiceDep) -> HistoryEventDetail:
    return service.get(event_id)
