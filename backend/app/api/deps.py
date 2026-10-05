"""FastAPI dependency providers.

Routes obtain settings, the database session, the signed-in user, and services
exclusively through these providers (API → Service → Repository → Database).
Infrastructure objects are built once in ``create_app`` and stored on ``app.state``.

Every user-data service is constructed with the signed-in user and only ever
returns that user's records.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import DatabaseNotConfiguredError
from app.core.rate_limit import RateLimiter
from app.db.models import User
from app.db.session import Database
from app.services.activity import HistoryService
from app.services.agent.actions import AgentActionService
from app.services.agent.service import AgentService
from app.services.ai.service import AIAssistant, AIService
from app.services.analysis.engine import AnalysisEngine
from app.services.analysis.service import AnalysisService
from app.services.auth import AuthService, NotAuthenticatedError
from app.services.files import FileService
from app.services.health import HealthService
from app.services.project_intelligence.service import ProjectIntelligenceService
from app.services.project_search.context import ProjectContextBuilder
from app.services.project_search.index import IndexCache
from app.services.project_search.service import ProjectSearchService
from app.services.projects import ProjectService
from app.services.retrieval.service import RetrievalService, SemanticRetriever


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service


def get_analysis_engine(request: Request) -> AnalysisEngine:
    engine: AnalysisEngine = request.app.state.analysis_engine
    return engine


def get_db_session(request: Request) -> Iterator[Session]:
    database: Database | None = request.app.state.database
    if database is None:
        raise DatabaseNotConfiguredError()
    with database.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
AnalysisEngineDep = Annotated[AnalysisEngine, Depends(get_analysis_engine)]
SessionDep = Annotated[Session, Depends(get_db_session)]


def get_login_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.login_limiter
    return limiter


def get_login_account_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.login_account_limiter
    return limiter


def get_register_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.register_limiter
    return limiter


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
LoginLimiterDep = Annotated[RateLimiter, Depends(get_login_limiter)]
LoginAccountLimiterDep = Annotated[RateLimiter, Depends(get_login_account_limiter)]
RegisterLimiterDep = Annotated[RateLimiter, Depends(get_register_limiter)]


# Tokens are issued by secrets.token_urlsafe(32): 43 URL-safe characters.
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def get_current_user(request: Request, settings: SettingsDep, auth: AuthServiceDep) -> User:
    """The signed-in, active user (from the session cookie), or 401 ``not_authenticated``."""
    token = request.cookies.get(settings.session_cookie_name)
    user = auth.user_for_token(token) if token and _TOKEN_SHAPE.match(token) else None
    if user is None:
        raise NotAuthenticatedError()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_project_service(session: SessionDep, settings: SettingsDep, user: CurrentUserDep) -> ProjectService:
    return ProjectService(session, settings, user)


def get_analysis_service(
    session: SessionDep, engine: AnalysisEngineDep, settings: SettingsDep, user: CurrentUserDep
) -> AnalysisService:
    return AnalysisService(session, engine, settings, user)


def get_file_service(
    session: SessionDep,
    settings: SettingsDep,
    analysis: Annotated[AnalysisService, Depends(get_analysis_service)],
    user: CurrentUserDep,
) -> FileService:
    return FileService(session, settings, analysis, user)


def get_intelligence_service(
    session: SessionDep, settings: SettingsDep, user: CurrentUserDep
) -> ProjectIntelligenceService:
    return ProjectIntelligenceService(session, settings, user)


def get_history_service(session: SessionDep, user: CurrentUserDep) -> HistoryService:
    return HistoryService(session, user)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
FileServiceDep = Annotated[FileService, Depends(get_file_service)]
IntelligenceServiceDep = Annotated[ProjectIntelligenceService, Depends(get_intelligence_service)]
HistoryServiceDep = Annotated[HistoryService, Depends(get_history_service)]


def get_ai_service(request: Request) -> AIService:
    service: AIService = request.app.state.ai_service
    return service


def get_index_cache(request: Request) -> IndexCache:
    cache: IndexCache = request.app.state.search_index_cache
    return cache


def get_retrieval_service(request: Request) -> RetrievalService:
    service: RetrievalService = request.app.state.retrieval_service
    return service


AIServiceDep = Annotated[AIService, Depends(get_ai_service)]
IndexCacheDep = Annotated[IndexCache, Depends(get_index_cache)]
RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]


def get_retriever(
    session: SessionDep, settings: SettingsDep, user: CurrentUserDep, service: RetrievalServiceDep
) -> SemanticRetriever:
    return SemanticRetriever(session, settings, user, service)


RetrieverDep = Annotated[SemanticRetriever, Depends(get_retriever)]


def get_search_service(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    cache: IndexCacheDep,
    retriever: RetrieverDep,
) -> ProjectSearchService:
    return ProjectSearchService(session, settings, user, cache, retriever=retriever)


SearchServiceDep = Annotated[ProjectSearchService, Depends(get_search_service)]


def get_context_builder(search: SearchServiceDep) -> ProjectContextBuilder:
    return ProjectContextBuilder(search)


def get_ai_assistant(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    ai: AIServiceDep,
    cache: IndexCacheDep,
    retriever: RetrieverDep,
) -> AIAssistant:
    return AIAssistant(session, settings, user, ai, cache, retriever=retriever)


ContextBuilderDep = Annotated[ProjectContextBuilder, Depends(get_context_builder)]
AIAssistantDep = Annotated[AIAssistant, Depends(get_ai_assistant)]


def get_agent_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.agent_limiter
    return limiter


def get_agent_service(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    ai: AIServiceDep,
    limiter: Annotated[RateLimiter, Depends(get_agent_limiter)],
    search: SearchServiceDep,
    builder: ContextBuilderDep,
    engine: AnalysisEngineDep,
) -> AgentService:
    return AgentService(session, settings, user, ai, limiter, search, builder, engine)


def get_agent_action_service(
    session: SessionDep, user: CurrentUserDep, files: FileServiceDep, projects: ProjectServiceDep
) -> AgentActionService:
    return AgentActionService(session, user, files, projects)


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
AgentActionServiceDep = Annotated[AgentActionService, Depends(get_agent_action_service)]
