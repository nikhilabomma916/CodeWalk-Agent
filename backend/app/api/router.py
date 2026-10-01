"""Version 1 API router. Each feature module contributes one router here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import ai, analysis, auth, files, health, history, meta, projects, search
from app.schemas.errors import ErrorResponse

api_v1_router = APIRouter(
    responses={
        422: {"model": ErrorResponse, "description": "Request validation failed."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    }
)
api_v1_router.include_router(health.router)
api_v1_router.include_router(meta.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(analysis.router)
api_v1_router.include_router(projects.router)
api_v1_router.include_router(files.router)
api_v1_router.include_router(history.router)
api_v1_router.include_router(search.router)
api_v1_router.include_router(ai.router)
