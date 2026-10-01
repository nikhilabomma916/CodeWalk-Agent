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
from app.core.rate_limit import AttemptLimiter
from app.db.models import User
from app.db.session import Database
from app.services.activity import HistoryService
from app.services.analysis.engine import AnalysisEngine
from app.services.analysis.service import AnalysisService
from app.services.auth import AuthService, NotAuthenticatedError
from app.services.files import FileService
from app.services.health import HealthService
from app.services.project_intelligence.service import ProjectIntelligenceService
from app.services.projects import ProjectService


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


def get_login_limiter(request: Request) -> AttemptLimiter:
    limiter: AttemptLimiter = request.app.state.login_limiter
    return limiter


def get_register_limiter(request: Request) -> AttemptLimiter:
    limiter: AttemptLimiter = request.app.state.register_limiter
    return limiter


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
LoginLimiterDep = Annotated[AttemptLimiter, Depends(get_login_limiter)]
RegisterLimiterDep = Annotated[AttemptLimiter, Depends(get_register_limiter)]


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
