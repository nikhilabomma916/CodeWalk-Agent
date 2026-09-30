"""FastAPI dependency providers.

Routes obtain settings and services exclusively through these providers.
Services are built once per application in ``main.create_app`` and stored on
``app.state``; later modules add repositories/DB sessions here so that routes
never construct infrastructure themselves (API -> Service -> Repository).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.health import HealthService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
