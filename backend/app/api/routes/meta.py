from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import SettingsDep
from app.schemas.health import ApiInfoResponse

router = APIRouter(tags=["meta"])
root_router = APIRouter(include_in_schema=False)

API_VERSION = "v1"


@root_router.get("/")
async def root(settings: SettingsDep) -> dict[str, str | None]:
    return {
        "name": settings.app_name,
        "api": settings.api_v1_prefix,
        "docs": "/docs" if settings.docs_are_enabled else None,
    }


@router.get(
    "/info",
    response_model=ApiInfoResponse,
    summary="API information",
    description="Public, non-sensitive metadata about the running API.",
)
async def info(settings: SettingsDep) -> ApiInfoResponse:
    return ApiInfoResponse(
        name=settings.app_name,
        version=__version__,
        api_version=API_VERSION,
        environment=settings.env.value,
        docs_url="/docs" if settings.docs_are_enabled else None,
    )
