"""AI services (Modules 7 and 8).

``AIService`` (one per application) owns provider selection, status, abuse
limits, and calling + validating the provider. ``AIAssistant`` (one per request)
adds the signed-in user's context: project ownership checks, project context
(Module 9 deterministic selection, plus Module 10 semantic matches when
available), normalization of the answer, and persistence.

Flow for every task:
  code + deterministic diagnostics -> (project context) -> prompt -> provider
  -> schema validation -> normalization against the real file -> response.
Nothing is executed and no file is modified: fix suggestions are proposals.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import request_id_var
from app.core.rate_limit import AttemptLimiter
from app.db.models import ActivityType, Analysis, AnalysisStatus, AnalysisType, Project, ProjectFile, User
from app.repositories.analyses import AnalysisRepository
from app.repositories.files import FileRepository
from app.schemas.ai import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIAnalysisType,
    AIExplainRequest,
    AIExplanationResponse,
    AIFinding,
    AIFixRequest,
    AIFixSuggestionResponse,
    AIRequestBase,
    AIStatusResponse,
    Basis,
    Confidence,
    ContextSummary,
    DiagnosticInput,
    FindingCategory,
    FindingSeverity,
    RelatedLocation,
)
from app.services.activity import ActivityRecorder
from app.services.ai import edits as edit_rules
from app.services.ai.base import (
    AIDisabledError,
    AIMalformedResponseError,
    AINotConfiguredError,
    AIProvider,
    StructuredRequest,
    StructuredResult,
)
from app.services.ai.outputs import ModelAnalysis, ModelExplanation, ModelFix, output_schema
from app.services.ai.prompts import code_analysis, explanation, fix
from app.services.ai.prompts.common import (
    ContextSnippet,
    render_context,
    render_diagnostics,
    render_file,
)
from app.services.ai.providers import UnknownProviderError, create_provider
from app.services.file_content import content_hash
from app.services.languages import detect_language
from app.services.project_search.context import ProjectContextBuilder
from app.services.project_search.index import IndexCache
from app.services.project_search.service import ProjectSearchService
from app.services.projects import ProjectService
from app.services.retrieval.service import SemanticRetriever

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# Larger files are sent as a window around the lines in question (with a warning).
MAX_CODE_CHARS = 100_000
WINDOW_LINES = 150
AI_HISTORY_PER_FILE = 20


class AIRequestLimitError(AppError):
    status_code = 429
    code = "too_many_ai_requests"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many AI requests. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


class InvalidSourceRangeError(AppError):
    status_code = 422
    code = "invalid_range"


class AIService:
    """Application-wide AI entry point (stored on ``app.state``)."""

    def __init__(self, settings: Settings, provider: AIProvider | None = None) -> None:
        self.settings = settings
        self.limiter = AttemptLimiter(settings.ai_max_requests, settings.ai_window_seconds)
        self.provider: AIProvider | None = provider
        self.provider_problem: str | None = None
        if provider is None and settings.ai_enabled:
            try:
                self.provider = create_provider(settings)
            except UnknownProviderError as exc:
                self.provider_problem = f"Unknown AI provider {exc.args[0]!r} (supported: anthropic)."

    def status(self) -> AIStatusResponse:
        enabled = self.settings.ai_enabled
        provider_status = self.provider.status() if self.provider is not None else None
        configured = provider_status is not None and provider_status.configured
        if not enabled:
            detail: str | None = "AI assistance is turned off (set CODEWALK_AI_ENABLED=true to enable it)."
        elif self.provider_problem:
            detail = self.provider_problem
        elif provider_status is not None and not provider_status.configured:
            detail = provider_status.detail
        else:
            detail = None
        return AIStatusResponse(
            enabled=enabled,
            configured=configured,
            available=enabled and configured,
            provider=provider_status.provider if provider_status else self.settings.ai_provider,
            model=provider_status.model if provider_status else None,
            detail=detail,
            analysis_types=list(AIAnalysisType),
        )

    def require_available(self, user: User) -> AIProvider:
        if not self.settings.ai_enabled:
            raise AIDisabledError()
        if self.provider is None:
            raise AINotConfiguredError(self.provider_problem or "No AI provider is configured.")
        state = self.provider.status()
        if not state.configured:
            raise AINotConfiguredError(state.detail or "The AI provider is not configured.")
        key = f"ai:{user.id}"
        if (retry_after := self.limiter.retry_after(key)) is not None:
            raise AIRequestLimitError(retry_after)
        self.limiter.record_failure(key)  # every request counts toward the limit
        return self.provider

    def run(
        self, provider: AIProvider, system: str, user: str, output: type[ModelT]
    ) -> tuple[ModelT, StructuredResult]:
        result = provider.generate_structured(
            StructuredRequest(
                system=system,
                user=user,
                schema=output_schema(output),
                max_tokens=self.settings.ai_max_tokens,
                timeout_seconds=self.settings.ai_timeout_seconds,
                effort=self.settings.ai_effort,
            )
        )
        try:
            return output.model_validate(result.data), result
        except ValidationError:
            logger.warning("AI answer failed schema validation (%s)", output.__name__)
            raise AIMalformedResponseError() from None


@dataclass
class _Prepared:
    """A request after validation: the code lines, the window sent, and context."""

    path: str
    language: str
    lines: list[str]
    window_start: int
    window_end: int
    file_block: str
    context_block: str
    context: ContextSummary
    project: Project | None = None
    file: ProjectFile | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return max(len(self.lines), 1)

    def in_window(self, line: int | None) -> bool:
        return line is not None and self.window_start <= line <= self.window_end


class AIAssistant:
    """Per-request AI operations for the signed-in user."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        owner: User,
        ai: AIService,
        search_cache: IndexCache,
        retriever: SemanticRetriever | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.ai = ai
        self.search_cache = search_cache
        self.retriever = retriever

    # --- preparation ---------------------------------------------------------------------

    def _check_size(self, code: str) -> None:
        if len(code.encode("utf-8")) > self.settings.max_source_bytes:
            raise AppError(
                f"Code is larger than {self.settings.max_source_bytes} bytes.",
                code="source_too_large",
                status_code=413,
            )

    def _check_diagnostic(self, diagnostic: DiagnosticInput, line_count: int) -> None:
        if diagnostic.line > line_count or diagnostic.end_line > line_count + 1:
            raise InvalidSourceRangeError(
                f"Diagnostic {diagnostic.id} points at line {diagnostic.line}, "
                f"but the code has {line_count} lines."
            )
        if (diagnostic.end_line, diagnostic.end_column) < (diagnostic.line, diagnostic.column):
            raise InvalidSourceRangeError(f"Diagnostic {diagnostic.id} ends before it starts.")

    def _prepare(
        self,
        request: AIRequestBase,
        *,
        focus_line: int | None,
        query: str | None = None,
        focus_diagnostics: Sequence[DiagnosticInput] = (),
    ) -> _Prepared:
        self._check_size(request.code)
        lines = request.code.splitlines()
        line_count = max(len(lines), 1)
        for diagnostic in request.diagnostics:
            self._check_diagnostic(diagnostic, line_count)
        language = (request.language or detect_language(request.file_path)).value
        warnings: list[str] = []

        start, end = 1, line_count
        if len(request.code) > MAX_CODE_CHARS:
            center = focus_line or 1
            start = max(1, center - WINDOW_LINES)
            end = min(line_count, center + WINDOW_LINES)
            warnings.append(f"The file is large; only lines {start}-{end} were sent to the AI provider.")
        file_block = render_file(
            request.file_path, language, lines[start - 1 : end] or [""], start, line_count
        )

        project = file = None
        context = ContextSummary(used=False)
        context_block = ""
        if request.project_id is not None:
            project = ProjectService(self.session, self.settings, self.owner).get(request.project_id)
            file = FileRepository(self.session).get_by_path(project.id, request.file_path)
            if file is None:
                raise NotFoundError("The file is not part of this project.", code="file_not_found")
            try:
                built = ProjectContextBuilder(
                    ProjectSearchService(
                        self.session, self.settings, self.owner, self.search_cache, retriever=self.retriever
                    )
                ).build(
                    project.id,
                    current_file=request.file_path,
                    current_content=request.code,
                    line=focus_line,
                    query=query,
                    diagnostics=list(focus_diagnostics) or request.diagnostics,
                )
            except NotFoundError:
                raise
            except Exception:  # context is an enhancement: never fail the request because of it
                logger.exception("Building project context failed")
                warnings.append("Project context was unavailable; the answer uses this file only.")
            else:
                snippets = [
                    ContextSnippet(s.file_path, s.start_line, s.lines, s.reason)
                    for s in built.snippets
                    if s.file_path != request.file_path
                ]
                context_block = render_context(snippets)
                semantic = built.metadata.get("semantic") or {}
                context = ContextSummary(
                    used=bool(snippets),
                    files=sorted({s.file_path for s in snippets}),
                    symbols=[s.qualified_name for s in built.symbols],
                    snippet_count=len(snippets),
                    semantic_snippet_count=sum(1 for s in snippets if s.reason.startswith("semantically")),
                    truncated=bool(built.metadata.get("truncated")),
                )
                rag_enabled = self.retriever is not None and self.retriever.service.settings.rag_enabled
                if rag_enabled and not semantic.get("used") and semantic.get("detail"):
                    detail = str(semantic["detail"]).rstrip(".")
                    warnings.append(
                        f"Semantic context was not added ({detail}); project context is deterministic."
                    )
        return _Prepared(
            path=request.file_path,
            language=language,
            lines=lines,
            window_start=start,
            window_end=end,
            file_block=file_block,
            context_block=context_block,
            context=context,
            project=project,
            file=file,
            warnings=warnings,
        )

    def _base(
        self, result: StructuredResult, prepared: _Prepared, confidence: str, warnings: Sequence[str]
    ) -> dict[str, Any]:
        provider = self.ai.provider
        return {
            "request_id": request_id_var.get() or "",
            "provider": provider.name if provider else "",
            "model": result.model,
            "generated_at": datetime.now(UTC),
            "confidence": Confidence(confidence),
            "warnings": [*prepared.warnings, *warnings],
            "context": prepared.context,
        }

    def _record(
        self,
        prepared: _Prepared,
        analysis_type: AnalysisType,
        activity: ActivityType,
        code: str,
        started: float,
        count: int,
        details: dict[str, Any],
        result: StructuredResult,
    ) -> uuid.UUID | None:
        """Persist an AI result for a project file (metadata and the validated answer, not the code)."""
        if prepared.project is None or prepared.file is None:
            return None
        provider = self.ai.provider
        analyses = AnalysisRepository(self.session)
        record: Analysis = analyses.create(
            project_id=prepared.project.id,
            file_id=prepared.file.id,
            analysis_type=analysis_type,
            status=AnalysisStatus.COMPLETED,
            language=prepared.language,
            content_hash=content_hash(code),
            duration_ms=round((time.perf_counter() - started) * 1000),
            diagnostic_count=count,
            details={
                "provider": provider.name if provider else None,
                "model": result.model,
                "provider_request_id": result.request_id,
                "usage": result.usage,
                **details,
            },
        )
        analyses.prune_file_history(prepared.file.id, keep=AI_HISTORY_PER_FILE, analysis_type=analysis_type)
        ActivityRecorder(self.session, self.owner).record(
            activity,
            prepared.project,
            file=prepared.file,
            analysis=record,
            details={
                "model": result.model,
                **{k: v for k, v in details.items() if k in ("analysis_type", "status", "diagnostic_id")},
            },
        )
        self.session.commit()
        return record.id

    # --- Module 7: analysis --------------------------------------------------------------

    def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResponse:
        provider = self.ai.require_available(self.owner)
        started = time.perf_counter()
        focus = request.selected_range.start_line if request.selected_range else None
        if request.selected_range and request.selected_range.end_line > max(
            len(request.code.splitlines()), 1
        ):
            raise InvalidSourceRangeError("The selected range is outside the code.")
        prepared = self._prepare(request, focus_line=focus)
        answer, result = self.ai.run(
            provider,
            code_analysis.SYSTEM,
            code_analysis.user_message(
                request.analysis_type,
                prepared.file_block,
                render_diagnostics(request.diagnostics),
                prepared.context_block,
                request.selected_range,
            ),
            ModelAnalysis,
        )
        diagnostic_ids = {d.id for d in request.diagnostics}
        findings: list[AIFinding] = []
        dropped = 0
        for index, item in enumerate(answer.findings, start=1):
            line, end_line = item.line, item.end_line
            if line is not None and not prepared.in_window(line):
                dropped += 1
                continue
            if end_line is not None and (line is None or end_line < line or end_line > prepared.line_count):
                end_line = line
            text = prepared.lines[line - 1] if line is not None and line <= len(prepared.lines) else ""
            findings.append(
                AIFinding(
                    id=f"ai-{index}",
                    severity=FindingSeverity(item.severity),
                    category=FindingCategory(item.category),
                    title=item.title.strip()[:200],
                    description=item.description.strip(),
                    reasoning=item.reasoning.strip(),
                    basis=Basis(item.basis),
                    file_path=request.file_path,
                    line=line,
                    column=(len(text) - len(text.lstrip()) + 1) if line is not None else None,
                    end_line=end_line,
                    end_column=(len(prepared.lines[end_line - 1]) + 1)
                    if end_line is not None and end_line <= len(prepared.lines)
                    else None,
                    confidence=Confidence(item.confidence),
                    suggestion=(item.suggestion or "").strip() or None,
                    related_diagnostic_id=item.related_diagnostic_id
                    if item.related_diagnostic_id in diagnostic_ids
                    else None,
                    metadata={"evidence": item.evidence[:2000]} if item.evidence else {},
                )
            )
        warnings = list(answer.warnings)
        if dropped:
            warnings.append(f"{dropped} finding(s) referred to lines outside the code and were discarded.")
        base = self._base(result, prepared, answer.confidence, warnings)
        record_id = self._record(
            prepared,
            AnalysisType.AI_REVIEW,
            ActivityType.AI_ANALYZED,
            request.code,
            started,
            len(findings),
            {
                "analysis_type": request.analysis_type.value,
                "summary": answer.summary,
                "findings": [f.model_dump(mode="json") for f in findings],
                "warnings": base["warnings"],
            },
            result,
        )
        return AIAnalysisResponse(
            **base,
            record_id=record_id,
            analysis_type=request.analysis_type,
            summary=answer.summary.strip(),
            findings=findings,
        )

    # --- Module 8: explanation -----------------------------------------------------------

    def explain(self, request: AIExplainRequest) -> AIExplanationResponse:
        provider = self.ai.require_available(self.owner)
        started = time.perf_counter()
        diagnostic = request.diagnostic
        self._check_diagnostic(diagnostic, max(len(request.code.splitlines()), 1))
        others = [d for d in request.diagnostics if d.id != diagnostic.id]
        prepared = self._prepare(
            request.model_copy(update={"diagnostics": [diagnostic, *others]}),
            focus_line=diagnostic.line,
            focus_diagnostics=[diagnostic],
        )
        answer, result = self.ai.run(
            provider,
            explanation.SYSTEM,
            explanation.user_message(
                diagnostic, prepared.file_block, render_diagnostics(others), prepared.context_block
            ),
            ModelExplanation,
        )
        allowed_paths = {request.file_path, *prepared.context.files}
        locations: list[RelatedLocation] = []
        dropped = 0
        for item in answer.related_locations:
            path = item.file_path.strip().lstrip("./")
            if path not in allowed_paths:
                dropped += 1
                continue
            line = item.line
            if path == request.file_path and line is not None and not 1 <= line <= prepared.line_count:
                line = None
            locations.append(RelatedLocation(file_path=path, line=line, reason=item.reason.strip()))
        warnings = list(answer.warnings)
        if dropped:
            warnings.append(f"{dropped} related location(s) outside the supplied code were discarded.")
        base = self._base(result, prepared, answer.confidence, warnings)
        record_id = self._record(
            prepared,
            AnalysisType.AI_EXPLANATION,
            ActivityType.AI_EXPLAINED,
            request.code,
            started,
            0,
            {
                "diagnostic_id": diagnostic.id,
                "diagnostic": diagnostic.model_dump(mode="json"),
                "explanation": answer.explanation,
                "cause": answer.cause,
                "impact": answer.impact,
                "suggested_fix": answer.suggested_fix,
            },
            result,
        )
        return AIExplanationResponse(
            **base,
            record_id=record_id,
            diagnostic_id=diagnostic.id,
            problem=diagnostic.message,
            explanation=answer.explanation.strip(),
            cause=answer.cause.strip(),
            impact=answer.impact.strip(),
            suggested_fix=answer.suggested_fix.strip(),
            related_code_locations=locations,
        )

    # --- Module 8: fix suggestion --------------------------------------------------------

    def fix_suggestion(self, request: AIFixRequest) -> AIFixSuggestionResponse:
        provider = self.ai.require_available(self.owner)
        started = time.perf_counter()
        line_count = max(len(request.code.splitlines()), 1)
        if request.diagnostic is not None:
            self._check_diagnostic(request.diagnostic, line_count)
        if len(request.code) > MAX_CODE_CHARS:
            # Edits are expressed in absolute line numbers; a partial file could not be patched safely.
            raise AppError(
                "Fix suggestions are limited to files under 100,000 characters.",
                code="source_too_large",
                status_code=413,
            )
        focus = request.diagnostic.line if request.diagnostic else None
        prepared = self._prepare(
            request,
            focus_line=focus,
            query=request.instruction,
            focus_diagnostics=[request.diagnostic] if request.diagnostic else (),
        )
        answer, result = self.ai.run(
            provider,
            fix.SYSTEM,
            fix.user_message(
                request.diagnostic,
                request.instruction,
                prepared.file_block,
                render_diagnostics(
                    [
                        d
                        for d in request.diagnostics
                        if request.diagnostic is None or d.id != request.diagnostic.id
                    ]
                ),
                prepared.context_block,
            ),
            ModelFix,
        )
        warnings = list(answer.warnings)
        suggested = request.code
        code_edits = []
        status = "no_suggestion"
        if answer.edits:
            try:
                code_edits = edit_rules.validate_edits(
                    request.file_path,
                    request.code,
                    edit_rules.line_edits_to_code_edits(request.file_path, request.code, answer.edits),
                )
                suggested = edit_rules.apply_edits(request.code, code_edits)
                edit_rules.check_change_is_safe(request.code, suggested)
            except edit_rules.InvalidEditError as exc:
                warnings.append(
                    f"The proposed change was discarded because it failed validation: {exc.message}"
                )
                code_edits, suggested = [], request.code
            else:
                status = "suggested" if suggested != request.code else "no_suggestion"
        if status == "no_suggestion" and answer.no_change_reason:
            warnings.append(answer.no_change_reason.strip())
        diff = edit_rules.unified_diff(request.file_path, request.code, suggested)
        base = self._base(result, prepared, answer.confidence, warnings)
        record_id = self._record(
            prepared,
            AnalysisType.AI_FIX_SUGGESTION,
            ActivityType.AI_FIX_SUGGESTED,
            request.code,
            started,
            len(code_edits),
            {
                "status": status,
                "diagnostic_id": request.diagnostic.id if request.diagnostic else None,
                "summary": answer.summary,
                "edits": [e.model_dump(mode="json") for e in code_edits],
            },
            result,
        )
        return AIFixSuggestionResponse(
            **base,
            record_id=record_id,
            status=status,
            summary=answer.summary.strip(),
            explanation=answer.explanation.strip(),
            file_path=request.file_path,
            original_code=request.code,
            original_hash=edit_rules.text_hash(request.code),
            suggested_code=suggested,
            diff=diff,
            edits=code_edits,
        )
