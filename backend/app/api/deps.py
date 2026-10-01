"""FastAPI dependency providers.

Routes obtain settings, the database session, and services exclusively through
these providers (API → Service → Repository → Database). Infrastructure objects
are built once in ``create_app`` and stored on ``app.state``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import DatabaseNotConfiguredError
from app.db.session import Database
from app.services.analysis.engine import AnalysisEngine
from app.services.analysis.service import AnalysisService
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


def get_project_service(session: SessionDep, settings: SettingsDep) -> ProjectService:
    return ProjectService(session, settings)


def get_analysis_service(
    session: SessionDep, engine: AnalysisEngineDep, settings: SettingsDep
) -> AnalysisService:
    return AnalysisService(session, engine, settings)


def get_file_service(
    session: SessionDep,
    settings: SettingsDep,
    analysis: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> FileService:
    return FileService(session, settings, analysis)


def get_intelligence_service(session: SessionDep, settings: SettingsDep) -> ProjectIntelligenceService:
    return ProjectIntelligenceService(session, settings)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
FileServiceDep = Annotated[FileService, Depends(get_file_service)]
IntelligenceServiceDep = Annotated[ProjectIntelligenceService, Depends(get_intelligence_service)]
