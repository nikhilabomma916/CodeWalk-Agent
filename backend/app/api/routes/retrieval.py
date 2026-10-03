"""Semantic retrieval endpoints (Module 10). All require a signed-in user.

Status never calls the embedding provider and never returns a credential.
Indexing reads only the caller's own project (404 for anyone else's).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, RetrievalServiceDep, RetrieverDep, SearchServiceDep
from app.schemas.errors import ErrorResponse
from app.schemas.retrieval import IndexRunResponse, IndexStatusResponse, RetrievalStatusResponse

router = APIRouter(prefix="/rag", tags=["retrieval"])
project_router = APIRouter(
    prefix="/projects/{project_id}/rag",
    tags=["retrieval"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project not found (or not yours)."},
    },
)


@router.get(
    "/status",
    response_model=RetrievalStatusResponse,
    summary="Whether semantic retrieval can be used",
    description="Configuration state only: nothing is sent to the provider and no credential is returned.",
    responses={401: {"model": ErrorResponse, "description": "Not signed in."}},
)
def retrieval_status(service: RetrievalServiceDep, _: CurrentUserDep) -> RetrievalStatusResponse:
    return service.status()


@project_router.get(
    "/index",
    response_model=IndexStatusResponse,
    summary="Semantic index status of a project",
    description="How many of the project's files have embeddings matching their current content.",
)
def index_status(
    project_id: uuid.UUID, search: SearchServiceDep, retriever: RetrieverDep
) -> IndexStatusResponse:
    project, index = search.project_index(project_id)
    return retriever.index_status(project, index)


@project_router.post(
    "/index",
    response_model=IndexRunResponse,
    summary="Index a project for semantic retrieval",
    description=(
        "Embeds new and changed files (chunks follow functions, classes, and methods). Unchanged chunks keep "
        "their stored vectors. One run embeds at most RAG_MAX_CHUNKS_PER_RUN chunks; `remaining_files` says "
        "whether to run again. Source code is sent to the configured embedding provider; nothing is executed."
    ),
    responses={
        429: {
            "model": ErrorResponse,
            "description": "Too many runs (`too_many_index_runs`) or provider rate limit "
            "(`rag_rate_limited`).",
        },
        502: {
            "model": ErrorResponse,
            "description": "Provider error (`rag_provider_error`, `rag_malformed_response`).",
        },
        503: {
            "model": ErrorResponse,
            "description": "Retrieval disabled (`rag_disabled`), not configured (`rag_not_configured`), or "
            "provider unreachable (`rag_unavailable`).",
        },
        504: {"model": ErrorResponse, "description": "Provider timeout (`rag_timeout`)."},
    },
)
def index_project(
    project_id: uuid.UUID, search: SearchServiceDep, retriever: RetrieverDep
) -> IndexRunResponse:
    project, index = search.project_index(project_id)
    return retriever.index_project(project, index)
