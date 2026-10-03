from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AnalysisEngineDep, AnalysisServiceDep
from app.schemas.analysis import AnalysisRecordDetail, AnalyzeCodeRequest, LanguageSupport
from app.schemas.errors import ErrorResponse
from app.services.analysis.models import AnalysisResult

router = APIRouter(tags=["analysis"])


@router.post(
    "/analysis/code",
    response_model=AnalysisResult,
    summary="Analyze source code",
    description=(
        "Deterministic static analysis of the submitted text for the editor's real-time diagnostics. "
        "The code is parsed and linted, **never executed**, and nothing is stored. `capabilities` "
        "states exactly which kinds of analysis ran for the language."
    ),
    responses={413: {"model": ErrorResponse, "description": "Source exceeds CODEWALK_MAX_SOURCE_BYTES."}},
)
def analyze_code(request: AnalyzeCodeRequest, engine: AnalysisEngineDep) -> AnalysisResult:
    return engine.analyze(request.code, language=request.language, file_path=request.file_path)


@router.get(
    "/analysis/languages",
    response_model=list[LanguageSupport],
    summary="Languages with analyzers",
    description="Languages that have at least one analyzer, and whether its tooling is available here.",
)
def analysis_languages(engine: AnalysisEngineDep) -> list[LanguageSupport]:
    support: list[LanguageSupport] = []
    for language in engine.registry.supported_languages():
        analyzers = engine.registry.for_language(language)
        reasons = [
            reason
            for analyzer in analyzers
            if (reason := getattr(analyzer, "unavailable_reason", lambda: None)()) is not None
        ]
        support.append(
            LanguageSupport(
                language=language,
                analyzers=[analyzer.name for analyzer in analyzers],
                available=not reasons,
                detail="; ".join(reasons) or None,
            )
        )
    return support


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisRecordDetail,
    summary="Get a stored analysis",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def get_analysis(analysis_id: uuid.UUID, service: AnalysisServiceDep) -> AnalysisRecordDetail:
    return AnalysisRecordDetail.build(*service.get(analysis_id))
