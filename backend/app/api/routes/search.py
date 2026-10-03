"""Project-aware search and context (Modules 9 and 10): owner-only, bounded.

Deterministic search is the default; ``mode`` adds semantic or hybrid retrieval when available.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import ContextBuilderDep, SearchServiceDep
from app.schemas.errors import ErrorResponse
from app.schemas.search import (
    ContextRequest,
    RelevantContext,
    SearchRequest,
    SearchResponse,
    Snippet,
    SnippetRequest,
)

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["search"],
    responses={
        401: {"model": ErrorResponse, "description": "Not signed in."},
        404: {"model": ErrorResponse, "description": "Project or file not found (or not yours)."},
        503: {"model": ErrorResponse, "description": "Database not configured or unavailable."},
    },
)


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search a project",
    description=(
        "Matches symbols (functions, classes, methods, ...), file names and paths, imports, identifiers, "
        "and source text of the project's stored files. Ranking is deterministic and explained per result "
        "(`score_details`, `match_reason`). With `mode: semantic` results come from code embeddings "
        "(cosine similarity); with `mode: hybrid` both lists are fused by reciprocal rank (`fusion`). "
        "Without semantic retrieval the response falls back to deterministic results (`mode_used`, "
        "`warnings`)."
    ),
)
def search_project(
    project_id: uuid.UUID, request: SearchRequest, service: SearchServiceDep
) -> SearchResponse:
    return service.search(project_id, request)


@router.post("/snippet", response_model=Snippet, summary="A bounded excerpt of a project file")
def project_snippet(project_id: uuid.UUID, request: SnippetRequest, service: SearchServiceDep) -> Snippet:
    return service.snippet(project_id, request)


@router.post(
    "/context",
    response_model=RelevantContext,
    summary="Related code for a file",
    description=(
        "The context the AI features use: the containing symbol, definitions of names in diagnostics, "
        "query matches, imported definitions, importers, and (when available) semantically similar code, "
        "within fixed size limits."
    ),
)
def project_context(
    project_id: uuid.UUID, request: ContextRequest, builder: ContextBuilderDep
) -> RelevantContext:
    return builder.build(
        project_id,
        current_file=request.current_file,
        line=request.line,
        query=request.query,
        current_symbol=request.current_symbol,
        diagnostics=request.diagnostics,
    )
