"""Project memory (Module 17): notes the developer saves for the AI about one project.

Owner-only. Written only through these endpoints (never by the model), bounded, and checked for
credentials before anything is stored.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.schemas.errors import ErrorResponse
from app.schemas.insights import MemoryCreate, MemoryItem, MemoryList
from app.services.memory import MAX_ITEMS, MemoryService


def get_memory_service(session: SessionDep, settings: SettingsDep, user: CurrentUserDep) -> MemoryService:
    return MemoryService(session, settings, user)


MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]

router = APIRouter(
    prefix="/projects/{project_id}/memory",
    tags=["memory"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project or item not found (or not yours)."},
    },
)


@router.get("", response_model=MemoryList, summary="What the AI remembers about this project")
def list_memory(project_id: uuid.UUID, service: MemoryServiceDep) -> MemoryList:
    items = [MemoryItem.model_validate(m) for m in service.items(project_id)]
    return MemoryList(items=items, limit=MAX_ITEMS)


@router.post(
    "",
    response_model=MemoryItem,
    status_code=status.HTTP_201_CREATED,
    summary="Save a note for the AI (a convention, decision, term, constraint, or preference)",
    responses={
        409: {"model": ErrorResponse, "description": "The project already holds the most items."},
        422: {"model": ErrorResponse, "description": "Invalid, or looks like a credential."},
    },
)
def add_memory(project_id: uuid.UUID, data: MemoryCreate, service: MemoryServiceDep) -> MemoryItem:
    return MemoryItem.model_validate(service.add(project_id, data))


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Forget a note")
def delete_memory(project_id: uuid.UUID, memory_id: uuid.UUID, service: MemoryServiceDep) -> Response:
    service.delete(project_id, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
