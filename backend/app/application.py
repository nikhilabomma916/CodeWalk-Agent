"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_v1_router
from app.api.routes import meta
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, BodySizeLimitMiddleware, RequestContextMiddleware
from app.services.health import HealthService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting %s %s (env=%s, docs=%s, cors_origins=%s)",
            settings.app_name,
            __version__,
            settings.env.value,
            "on" if settings.docs_are_enabled else "off",
            ",".join(settings.cors_origins) or "-",
        )
        yield
        logger.info("Shutting down %s", settings.app_name)

    docs = settings.docs_are_enabled
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Backend API for CodeWalk Agent, an AI-assisted coding environment.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json" if docs else None,
    )

    app.state.settings = settings
    app.state.health_service = HealthService(
        service_name=settings.app_name,
        version=__version__,
        environment=settings.env.value,
        check_timeout_seconds=settings.health_check_timeout_seconds,
    )

    register_exception_handlers(app)

    # Middleware added last runs first: CORS -> request context -> body limit -> routes.
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    app.include_router(meta.root_router)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app
