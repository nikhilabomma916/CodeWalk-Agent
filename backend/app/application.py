"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
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
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    OriginCheckMiddleware,
    RequestContextMiddleware,
)
from app.core.rate_limit import RateLimiter, make_limiter
from app.db.session import Database, DatabaseHealthCheck
from app.services.ai.service import COMPLETION_MAX_REQUESTS, COMPLETION_WINDOW_SECONDS, AIService
from app.services.analysis.engine import AnalysisEngine
from app.services.analysis.typescript_worker import TypeScriptWorker, TypeScriptWorkerError
from app.services.github.client import GitHubClient
from app.services.health import HealthService
from app.services.health_checks import (
    ConfigurationHealthCheck,
    SchemaHealthCheck,
    TypeScriptWorkerHealthCheck,
)
from app.services.project_search.index import IndexCache
from app.services.retrieval.service import RetrievalService

logger = logging.getLogger(__name__)


def _warm_up(worker: TypeScriptWorker) -> None:
    """Start the TypeScript worker in the background so the first edit is fast."""
    if worker.unavailable_reason():
        logger.warning("TypeScript analysis unavailable: %s", worker.unavailable_reason())
        return
    try:
        worker.analyze("warmup.ts", "export {};", timeout=30)
    except TypeScriptWorkerError as exc:
        logger.warning("TypeScript analyzer warm-up failed: %s", exc)


def create_app(settings: Settings | None = None, *, warm_up: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    typescript_worker = TypeScriptWorker(settings.node_binary)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting %s %s (env=%s, docs=%s, cors_origins=%s)",
            settings.app_name,
            __version__,
            settings.env.value,
            "on" if settings.docs_are_enabled else "off",
            ",".join(settings.allowed_origins) or "-",
        )
        ai_status = app.state.ai_service.status()
        logger.info(
            "AI assistance: %s",
            f"available ({ai_status.provider}, {ai_status.model})" if ai_status.available else "unavailable",
        )
        rag_status = app.state.retrieval_service.status()
        logger.info(
            "Semantic retrieval: %s",
            f"available ({rag_status.provider}, {rag_status.model})"
            if rag_status.available
            else "unavailable",
        )
        logger.info(
            "Persistence: %s; workspace scanning: %s",
            "configured" if database else "not configured (CODEWALK_DATABASE_URL unset)",
            "enabled" if settings.workspace_root else "disabled",
        )
        if warm_up:
            threading.Thread(target=_warm_up, args=(typescript_worker,), daemon=True).start()
        yield
        logger.info("Shutting down %s", settings.app_name)
        typescript_worker.close()
        app.state.github_client.close()
        if database is not None:
            database.dispose()

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
        checks=[
            DatabaseHealthCheck(database, required=settings.is_production),
            SchemaHealthCheck(database, required=settings.is_production),
            TypeScriptWorkerHealthCheck(typescript_worker),
        ],
    )
    app.state.database = database
    app.state.analysis_engine = AnalysisEngine.create_default(
        max_source_bytes=settings.max_source_bytes,
        timeout_seconds=settings.analysis_timeout_seconds,
        typescript_worker=typescript_worker,
    )

    # Limits are shared by every API instance through PostgreSQL when a database is configured
    # (serverless and multi-instance hosting), and kept per process otherwise.
    engine = database.engine if database is not None else None

    def limiter(namespace: str, max_attempts: int, window_seconds: float) -> RateLimiter:
        return make_limiter(engine, max_attempts, window_seconds, namespace=namespace)

    app.state.ai_service = AIService(settings)
    app.state.ai_service.limiter = limiter("ai", settings.ai_max_requests, settings.ai_window_seconds)
    app.state.ai_service.completion_limiter = limiter(
        "ai-complete", COMPLETION_MAX_REQUESTS, COMPLETION_WINDOW_SECONDS
    )
    app.state.search_index_cache = IndexCache()
    app.state.retrieval_service = RetrievalService(settings)
    app.state.retrieval_service.query_limiter = limiter(
        "rag-query", settings.rag_max_queries, settings.rag_window_seconds
    )
    app.state.retrieval_service.index_limiter = limiter(
        "rag-index", settings.rag_max_index_runs, settings.rag_window_seconds
    )
    app.state.agent_limiter = limiter("agent", settings.agent_max_runs, settings.agent_window_seconds)
    app.state.login_limiter = limiter("login", settings.login_max_attempts, settings.login_window_seconds)
    app.state.login_account_limiter = limiter(
        "login-account", settings.login_account_max_attempts, settings.login_window_seconds
    )
    app.state.register_limiter = limiter(
        "register", settings.register_max_attempts, settings.register_window_seconds
    )
    ai_service, retrieval_service = app.state.ai_service, app.state.retrieval_service

    def ai_state() -> tuple[bool, bool, str | None]:
        state = ai_service.status()
        return state.enabled, state.configured, state.detail

    def embedding_state() -> tuple[bool, bool, str | None]:
        state = retrieval_service.status()
        return state.enabled, state.configured, None

    app.state.health_service.register(ConfigurationHealthCheck("ai_provider", ai_state))
    app.state.health_service.register(ConfigurationHealthCheck("embeddings", embedding_state))
    app.state.github_client = GitHubClient(timeout_seconds=settings.github_timeout_seconds)
    app.state.github_import_limiter = limiter(
        "github-import", settings.github_import_max_runs, settings.github_import_window_seconds
    )

    register_exception_handlers(app)

    # Middleware added last runs first: CORS -> request context -> origin check -> body limit -> routes.
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.request_body_limit)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(
        RequestContextMiddleware, api_prefix=settings.api_v1_prefix, hsts=settings.is_production
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    app.include_router(meta.root_router)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app
