"""Version 1 API router. Each feature module contributes one router here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, meta
from app.schemas.errors import ErrorResponse

api_v1_router = APIRouter(
    responses={
        422: {"model": ErrorResponse, "description": "Request validation failed."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    }
)
api_v1_router.include_router(health.router)
api_v1_router.include_router(meta.router)
