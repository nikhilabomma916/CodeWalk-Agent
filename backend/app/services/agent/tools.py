"""The agent's tools: thin, typed wrappers around existing CodeWalk services.

Every tool has a stable name, a description the model sees, a validated input
model (``extra="forbid"``), a validated output model, and a permission level.
Tools read only the signed-in user's project through the Module 9 index (stored
files, minus ignored folders and secret files) and never touch the filesystem,
run code, or execute shell/SQL. File paths are validated as project-relative
paths and must exist in the project index.

Nothing here writes a file. ``propose_fix`` (PROPOSED_CHANGE) only stores a
proposal; applying one is a separate, explicitly approved request.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import ActivityEvent, AgentAction, AgentActionStatus, Project, ProjectFile, User
from app.repositories.files import FileRepository
from app.schemas.agent import AgentRunRequest, ProposedChange, ToolPermission
from app.schemas.ai import CodeEdit, DiagnosticInput
from app.schemas.common import ProjectFilePath
from app.schemas.search import MatchType, SearchFilters, SearchMode, SearchRequest
from app.services import insights
from app.services.ai import edits as edit_rules
from app.services.ai.outputs import ModelLineEdit
from app.services.analysis.engine import AnalysisEngine
from app.services.project_intelligence.models import SymbolKind
from app.services.project_intelligence.scanner import is_secret_path
from app.services.project_search.context import ProjectContextBuilder, containing_symbol
from app.services.project_search.index import IndexedFile, ProjectIndex, is_searchable
from app.services.project_search.service import ProjectSearchService, make_snippet

MAX_FILE_LINES = 200  # get_file_content
MAX_LINE_CHARS = 400
MAX_RESULTS = 10
MAX_DIAGNOSTICS = 50
MAX_FINDINGS = 20
MAX_PROPOSAL_FILES = 10
MAX_NEW_FILE_CHARS = 100_000
_path_adapter: TypeAdapter[str] = TypeAdapter(ProjectFilePath)


class ToolError(AppError):
    """A tool could not do what was asked (bad path, missing file, invalid edit, ...).

    The message is shown to the model as the tool result and to the user as a failed step.
    """

    status_code = 422
    code = "tool_error"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolContext:
    """Everything a tool may use, scoped to one user's project for one run."""

    session: Session
    settings: Settings
    owner: User
    project: Project
    index: ProjectIndex
    search: ProjectSearchService
    context_builder: ProjectContextBuilder
    engine: AnalysisEngine
    request: AgentRunRequest
    run_id: Any
    actions: list[AgentAction] = field(default_factory=list)
    # Module 17: files the agent actually looked at (shown to the developer), and review findings.
    inspected: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)

    # --- shared helpers -------------------------------------------------------------------

    def file(self, raw_path: str) -> IndexedFile:
        """A searchable file of this project, or a ToolError. Never resolves outside the project."""
        try:
            path = _path_adapter.validate_python(raw_path)
        except ValidationError:
            raise ToolError(f"{raw_path!r} is not a valid project file path.", code="invalid_path") from None
        indexed = self.index.files.get(path)
        if indexed is None:
            raise ToolError(
                f"{path} is not a file of this project (or it cannot be read).", code="file_not_found"
            )
        if path not in self.inspected:
            self.inspected.append(path)
        return indexed

    def lines_of(self, file: IndexedFile) -> list[str]:
        """The file's lines as the developer sees them (the unsaved editor buffer for the open file)."""
        if file.path == self.request.file_path and self.request.code is not None:
            return self.request.code.splitlines()
        if file.lines is None:
            raise ToolError(
                f"{file.path} has no stored text content (binary or too large).", code="no_content"
            )
        return file.lines

    def content_of(self, file: IndexedFile) -> str:
        if file.path == self.request.file_path and self.request.code is not None:
            return self.request.code
        record = FileRepository(self.session).get_by_path(self.project.id, file.path)
        if record is None or record.content is None:
            raise ToolError(f"{file.path} has no stored text content.", code="no_content")
        return record.content

    def stored(self, file: IndexedFile) -> ProjectFile:
        record = FileRepository(self.session).get_by_path(self.project.id, file.path)
        if record is None or record.content is None:
            raise ToolError(f"{file.path} has no stored text content.", code="no_content")
        return record


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + "…"


def _diagnostic_row(d: DiagnosticInput) -> dict[str, Any]:
    return {
        "id": d.id,
        "severity": d.severity.value,
        "source": d.source,
        "code": d.code,
        "line": d.line,
        "column": d.column,
        "message": d.message,
    }


# --- tool inputs and outputs ---------------------------------------------------------------


class NoArgs(_Args):
    pass


class FileArgs(_Args):
    file_path: str = Field(max_length=1024)


class DiagnosticsOut(BaseModel):
    file_path: str | None
    source: str
    diagnostics: list[dict[str, Any]]
    note: str | None = None


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=200)
    symbol_type: SymbolKind | None = None
    limit: int = Field(default=8, ge=1, le=MAX_RESULTS)


class SearchHit(BaseModel):
    file_path: str
    line: int | None
    end_line: int | None
    symbol: str | None
    kind: str | None
    match: str
    preview: list[str]
    similarity: float | None = None


class SearchOut(BaseModel):
    mode_used: str
    total: int
    results: list[SearchHit]
    warnings: list[str]


class ContextArgs(_Args):
    file_path: str = Field(max_length=1024)
    line: int | None = Field(default=None, ge=1, le=1_000_000)
    query: str | None = Field(default=None, max_length=200)


class Excerpt(BaseModel):
    file_path: str
    start_line: int
    lines: list[str]
    reason: str


class ContextOut(BaseModel):
    strategy: str
    containing_symbol: str | None
    snippets: list[Excerpt]
    truncated: bool


class FileContentArgs(_Args):
    file_path: str = Field(max_length=1024)
    start_line: int = Field(default=1, ge=1, le=1_000_000)
    end_line: int | None = Field(default=None, ge=1, le=1_000_000)


class FileContentOut(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    lines: list[str]
    unsaved_editor_content: bool
    truncated: bool


class SymbolArgs(_Args):
    name: str = Field(min_length=1, max_length=200)


class SymbolOut(BaseModel):
    definitions: list[Excerpt]


class ExplainArgs(_Args):
    diagnostic_id: str = Field(min_length=1, max_length=100)


class ExplainOut(BaseModel):
    diagnostic: dict[str, Any]
    file_path: str
    code_around: Excerpt
    containing_symbol: str | None
    related: list[Excerpt]


class FixArgs(_Args):
    file_path: str = Field(max_length=1024)
    summary: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1, max_length=4000)
    edits: list[ModelLineEdit] = Field(min_length=1, max_length=edit_rules.MAX_EDITS)
    confidence: Literal["low", "medium", "high"] | None = None
    risk: Literal["low", "medium", "high"] | None = None


class FileEdits(_Args):
    file_path: str = Field(max_length=1024)
    edits: list[ModelLineEdit] = Field(min_length=1, max_length=edit_rules.MAX_EDITS)


class ChangesArgs(_Args):
    summary: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1, max_length=4000)
    files: list[FileEdits] = Field(min_length=1, max_length=10)
    confidence: Literal["low", "medium", "high"] | None = None
    risk: Literal["low", "medium", "high"] | None = None


class NewFileArgs(_Args):
    file_path: str = Field(max_length=1024)
    content: str = Field(min_length=1, max_length=100_000)
    summary: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1, max_length=4000)
    confidence: Literal["low", "medium", "high"] | None = None


class ChangesOut(BaseModel):
    group_id: str
    action_ids: list[str]
    files: list[str]
    changed_lines: int
    status: str
    note: str


class FixOut(BaseModel):
    action_id: str
    file_path: str
    changed_lines: int
    status: str
    note: str


# --- tool implementations -----------------------------------------------------------------


def get_diagnostics(ctx: ToolContext, _: NoArgs) -> tuple[DiagnosticsOut, str]:
    rows = [_diagnostic_row(d) for d in ctx.request.diagnostics[:MAX_DIAGNOSTICS]]
    out = DiagnosticsOut(
        file_path=ctx.request.file_path,
        source="problems shown in the developer's editor",
        diagnostics=rows,
        note=None if rows else "No problems are shown for the open file.",
    )
    return out, f"{len(rows)} problem(s) in the open file"


def analyze_code(ctx: ToolContext, args: FileArgs) -> tuple[DiagnosticsOut, str]:
    file = ctx.file(args.file_path)
    content = "\n".join(ctx.lines_of(file))
    result = ctx.engine.analyze(content, file_path=file.path)
    rows = [
        {
            "severity": d.severity.value,
            "source": d.source,
            "code": d.code,
            "line": d.line,
            "column": d.column,
            "message": d.message,
        }
        for d in result.diagnostics[:MAX_DIAGNOSTICS]
    ]
    out = DiagnosticsOut(
        file_path=file.path,
        source=f"deterministic analysis ({result.language.value}); the code was not executed",
        diagnostics=rows,
        note=None if rows else "No problems found.",
    )
    return out, f"Analyzed {file.path}: {len(rows)} problem(s)"


def _hits(ctx: ToolContext, results: list[Any]) -> list[SearchHit]:
    hits = []
    for r in results:
        preview = [_clip(line) for line in (r.snippet.lines[:6] if r.snippet else [])]
        hits.append(
            SearchHit(
                file_path=r.file_path,
                line=r.line,
                end_line=r.end_line,
                symbol=r.qualified_name or r.symbol_name,
                kind=r.symbol_type.value if r.symbol_type else None,
                match=r.match_type.value,
                preview=preview,
                similarity=r.semantic_similarity,
            )
        )
    return hits


def _search(ctx: ToolContext, args: SearchArgs, mode: SearchMode) -> SearchOut:
    current = ctx.request.file_path if ctx.request.file_path in ctx.index.files else None
    response = ctx.search.search(
        ctx.project.id,
        SearchRequest(
            query=args.query,
            limit=args.limit,
            current_file=current,
            filters=SearchFilters(symbol_type=args.symbol_type),
            mode=mode,
        ),
    )
    return SearchOut(
        mode_used=response.mode_used.value,
        total=response.total,
        results=_hits(ctx, response.results),
        warnings=response.warnings,
    )


def search_project(ctx: ToolContext, args: SearchArgs) -> tuple[SearchOut, str]:
    out = _search(ctx, args, SearchMode.DETERMINISTIC)
    files = len({h.file_path for h in out.results})
    return out, f"Found {out.total} result(s) in {files} file(s)"


def semantic_search_project(ctx: ToolContext, args: SearchArgs) -> tuple[SearchOut, str]:
    out = _search(ctx, args, SearchMode.HYBRID)
    if out.mode_used == "deterministic":
        return out, f"Semantic retrieval unavailable; deterministic search found {out.total} result(s)"
    semantic = sum(1 for h in out.results if h.similarity is not None)
    return out, f"Retrieved {len(out.results)} result(s), {semantic} by semantic similarity"


def get_project_context(ctx: ToolContext, args: ContextArgs) -> tuple[ContextOut, str]:
    file = ctx.file(args.file_path)
    current = ctx.request.code if file.path == ctx.request.file_path else None
    diagnostics = ctx.request.diagnostics if file.path == ctx.request.file_path else []
    built = ctx.context_builder.build(
        ctx.project.id,
        current_file=file.path,
        current_content=current,
        line=args.line,
        query=args.query,
        diagnostics=diagnostics,
    )
    snippets = [
        Excerpt(
            file_path=s.file_path, start_line=s.start_line, lines=[_clip(x) for x in s.lines], reason=s.reason
        )
        for s in built.snippets
    ]
    out = ContextOut(
        strategy=str(built.metadata.get("strategy")),
        containing_symbol=built.containing_symbol.qualified_name if built.containing_symbol else None,
        snippets=snippets,
        truncated=bool(built.metadata.get("truncated")),
    )
    files = len({s.file_path for s in snippets})
    return out, f"Collected {len(snippets)} related snippet(s) from {files} file(s)"


def get_file_content(ctx: ToolContext, args: FileContentArgs) -> tuple[FileContentOut, str]:
    file = ctx.file(args.file_path)
    lines = ctx.lines_of(file)
    total = len(lines)
    if total == 0:
        return (
            FileContentOut(
                file_path=file.path,
                start_line=1,
                end_line=0,
                total_lines=0,
                lines=[],
                unsaved_editor_content=False,
                truncated=False,
            ),
            f"{file.path} is empty",
        )
    start = min(args.start_line, total)
    requested_end = args.end_line or total
    if requested_end < start:
        raise ToolError("end_line is before start_line.", code="invalid_range")
    end = min(requested_end, total, start + MAX_FILE_LINES - 1)
    unsaved = file.path == ctx.request.file_path and ctx.request.code is not None
    out = FileContentOut(
        file_path=file.path,
        start_line=start,
        end_line=end,
        total_lines=total,
        lines=[_clip(line) for line in lines[start - 1 : end]],
        unsaved_editor_content=unsaved,
        truncated=end < min(requested_end, total),
    )
    return out, f"Read {file.path} lines {start}-{end}"


def get_symbol(ctx: ToolContext, args: SymbolArgs) -> tuple[SymbolOut, str]:
    response = ctx.search.search(
        ctx.project.id,
        SearchRequest(
            query=args.name,
            limit=5,
            filters=SearchFilters(match_types=[MatchType.SYMBOL_EXACT, MatchType.SYMBOL_PREFIX]),
        ),
    )
    definitions: list[Excerpt] = []
    for r in response.results:
        indexed = ctx.index.files.get(r.file_path)
        if indexed is None or r.line is None:
            continue
        snippet = make_snippet(indexed, r.line, r.end_line or r.line, max_lines=40)
        if snippet is not None:
            definitions.append(
                Excerpt(
                    file_path=r.file_path,
                    start_line=snippet.start_line,
                    lines=[_clip(x) for x in snippet.lines],
                    reason=f"{r.symbol_type.value if r.symbol_type else 'symbol'} {r.qualified_name}",
                )
            )
    return SymbolOut(definitions=definitions), f"Found {len(definitions)} definition(s) of {args.name}"


def explain_error(ctx: ToolContext, args: ExplainArgs) -> tuple[ExplainOut, str]:
    diagnostic = next((d for d in ctx.request.diagnostics if d.id == args.diagnostic_id), None)
    if diagnostic is None or ctx.request.file_path is None:
        raise ToolError(
            f"No problem with id {args.diagnostic_id!r} is shown in the open file.",
            code="diagnostic_not_found",
        )
    file = ctx.file(ctx.request.file_path)
    lines = ctx.lines_of(file)
    start = max(1, diagnostic.line - 6)
    end = min(len(lines), diagnostic.end_line + 6)
    built = ctx.context_builder.build(
        ctx.project.id,
        current_file=file.path,
        current_content=ctx.request.code,
        line=diagnostic.line,
        diagnostics=[diagnostic],
    )
    related = [
        Excerpt(
            file_path=s.file_path, start_line=s.start_line, lines=[_clip(x) for x in s.lines], reason=s.reason
        )
        for s in built.snippets
    ]
    symbol = containing_symbol(file.symbols, diagnostic.line)
    out = ExplainOut(
        diagnostic=_diagnostic_row(diagnostic),
        file_path=file.path,
        code_around=Excerpt(
            file_path=file.path,
            start_line=start,
            lines=[_clip(x) for x in lines[start - 1 : end]],
            reason="code around the problem",
        ),
        containing_symbol=(built.containing_symbol.qualified_name if built.containing_symbol else None)
        or (symbol.qualified_name if symbol else None),
        related=related,
    )
    return out, f"Collected evidence for “{diagnostic.message[:80]}” and {len(related)} related snippet(s)"


# --- Module 17: architecture, impact, references, tests, review findings ----------------------


class ImpactArgs(_Args):
    file_path: str = Field(max_length=1024)
    symbol: str | None = Field(default=None, max_length=200)


class NameArgs(_Args):
    name: str = Field(min_length=1, max_length=200)


class TestsOut(BaseModel):
    file_path: str
    tests: list[insights.Location]


Confidence = Literal["low", "medium", "high"]
Severity = Literal["info", "low", "medium", "high", "critical"]
FindingCategory = Literal[
    "correctness",
    "bug",
    "security",
    "performance",
    "maintainability",
    "architecture",
    "error_handling",
    "concurrency",
    "testing",
    "accessibility",
    "api_contract",
    "database",
]


class FindingArgs(_Args):
    severity: Severity
    category: FindingCategory
    title: str = Field(min_length=3, max_length=120)
    file_path: str = Field(max_length=1024)
    start_line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)
    explanation: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=600, description="What in the code shows this.")
    suggestion: str = Field(default="", max_length=600)
    confidence: Confidence


class FindingOut(BaseModel):
    finding_id: str
    recorded: int
    note: str


def _symbol_name(name: str | None) -> str | None:
    if name is None:
        return None
    if not re.fullmatch(r"[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*", name):
        raise ToolError(
            "symbol must be an identifier such as login or AuthService.verify.", code="invalid_symbol"
        )
    return name


MAX_ACTIVITY_EVENTS = 40
_ACTIVITY_KINDS = {"project": "project.", "files": "file.", "ai": "ai.", "agent": "agent."}


class ActivityArgs(_Args):
    limit: int = Field(default=20, ge=1, le=MAX_ACTIVITY_EVENTS, description="Most recent events to return.")
    since_days: int | None = Field(
        default=None, ge=1, le=365, description="Only events from the last N days."
    )
    kind: Literal["all", "project", "files", "ai", "agent"] = Field(
        default="all", description="Only project, file, AI, or agent events."
    )


class ActivityItem(BaseModel):
    at: datetime
    type: str
    file_path: str | None
    details: dict[str, Any]


class ActivityOut(BaseModel):
    project: str
    events: list[ActivityItem]
    note: str


def _compact_details(details: dict[str, Any]) -> dict[str, Any]:
    """Scalar values only, short strings, few keys: enough to say what happened, nothing more."""
    out: dict[str, Any] = {}
    for key, value in list(details.items())[:8]:
        if isinstance(value, bool | int | float) or value is None:
            out[key] = value
        elif isinstance(value, str):
            out[key] = value[:120]
    return out


def get_project_activity(ctx: ToolContext, args: ActivityArgs) -> tuple[ActivityOut, str]:
    """What the developer did in this project (created/edited/analyzed files, AI and agent use), newest
    first. Only this user's events for this project."""
    query = select(ActivityEvent).where(
        ActivityEvent.project_id == ctx.project.id, ActivityEvent.user_id == ctx.owner.id
    )
    if args.since_days is not None:
        query = query.where(ActivityEvent.created_at >= datetime.now(UTC) - timedelta(days=args.since_days))
    prefix = _ACTIVITY_KINDS.get(args.kind)
    rows = ctx.session.scalars(
        query.order_by(ActivityEvent.created_at.desc()).limit(MAX_ACTIVITY_EVENTS * 3)
    ).all()
    events = [
        ActivityItem(
            at=row.created_at,
            type=row.event_type.value,
            file_path=row.file_path,
            details=_compact_details(row.details or {}),
        )
        for row in rows
        if prefix is None or row.event_type.value.startswith(prefix)
    ][: args.limit]
    note = "Activity is what was recorded in CodeWalk (file saves, analyses, AI and agent use); "
    note += "it does not include work done outside CodeWalk or git history."
    return ActivityOut(project=ctx.project.name, events=events, note=note), (
        f"Read {len(events)} recent activity event(s)"
    )


def get_architecture(ctx: ToolContext, _: NoArgs) -> tuple[insights.ArchitectureReport, str]:
    report = insights.architecture(ctx.index)
    # Keep the tool result compact: the model sees the biggest parts of each list.
    report = report.model_copy(
        update={
            "components": report.components[:15],
            "links": report.links[:25],
            "api_routes": report.api_routes[:30],
            "data_models": report.data_models[:30],
            "entry_points": report.entry_points[:15],
        }
    )
    return (
        report,
        f"Summarized the architecture: {len(report.components)} component(s), {report.files} file(s)",
    )


def analyze_impact(ctx: ToolContext, args: ImpactArgs) -> tuple[insights.ImpactReport, str]:
    file = ctx.file(args.file_path)
    report = insights.impact(ctx.index, file.path, _symbol_name(args.symbol))
    affected = len(report.direct_dependents) + len(report.indirect_dependents)
    target = f"{args.symbol} in {file.path}" if args.symbol else file.path
    return report, (
        f"Impact of changing {target}: {affected} dependent file(s), "
        f"{len(report.possible_references)} possible reference(s), "
        f"{len(report.related_tests)} related test(s)"
    )


def find_references(ctx: ToolContext, args: NameArgs) -> tuple[insights.ReferenceReport, str]:
    report = insights.references(ctx.index, _symbol_name(args.name) or args.name)
    return (
        report,
        f"Found {len(report.definitions)} definition(s) and {len(report.references)} referencing file(s)",
    )


def find_related_tests(ctx: ToolContext, args: FileArgs) -> tuple[TestsOut, str]:
    file = ctx.file(args.file_path)
    tests = insights.related_tests(ctx.index, file.path)
    return TestsOut(file_path=file.path, tests=tests), f"Found {len(tests)} related test file(s)"


def record_finding(ctx: ToolContext, args: FindingArgs) -> tuple[FindingOut, str]:
    """Add a review finding to this run's report, after checking it points at real project lines."""
    if len(ctx.findings) >= MAX_FINDINGS:
        raise ToolError(
            f"At most {MAX_FINDINGS} findings can be recorded in one request.", code="finding_limit"
        )
    file = ctx.file(args.file_path)
    lines = ctx.lines_of(file)
    end = args.end_line or args.start_line
    if end < args.start_line or end > max(len(lines), 1):
        raise ToolError(
            f"Lines {args.start_line}-{end} are outside {file.path} ({len(lines)} lines).",
            code="invalid_range",
        )
    finding: dict[str, Any] = {
        "id": f"F{len(ctx.findings) + 1}",
        "severity": args.severity,
        "category": args.category,
        "title": args.title.strip(),
        "file_path": file.path,
        "start_line": args.start_line,
        "end_line": end,
        "explanation": args.explanation.strip(),
        "evidence": args.evidence.strip(),
        "suggestion": args.suggestion.strip(),
        "confidence": args.confidence,
        "excerpt": [_clip(line) for line in lines[args.start_line - 1 : min(end, args.start_line + 5)]],
    }
    ctx.findings.append(finding)
    return (
        FindingOut(
            finding_id=finding["id"],
            recorded=len(ctx.findings),
            note="Recorded in the review report. Nothing was changed.",
        ),
        f"Recorded a {args.severity} {args.category.replace('_', ' ')} finding "
        f"in {file.path}:{args.start_line}",
    )


def propose_fix(ctx: ToolContext, args: FixArgs) -> tuple[FixOut, str]:
    """Validate line edits against the SAVED file and store them as a pending proposal."""
    file = ctx.file(args.file_path)
    if ctx.project.root_path is not None:
        raise ToolError(
            "This project is linked to a server folder and cannot be edited.", code="project_read_only"
        )
    record = ctx.stored(file)
    base = record.content or ""
    if len(base) > 100_000:
        raise ToolError(
            "Changes can only be proposed for files under 100,000 characters.", code="file_too_large"
        )
    try:
        code_edits = edit_rules.validate_edits(
            file.path, base, edit_rules.line_edits_to_code_edits(file.path, base, args.edits)
        )
        suggested = edit_rules.apply_edits(base, code_edits)
        edit_rules.check_change_is_safe(base, suggested)
    except edit_rules.InvalidEditError as exc:
        raise ToolError(f"The proposed edits are invalid: {exc.message}", code="invalid_edit") from None
    if suggested == base:
        raise ToolError("The proposed edits do not change the file.", code="no_change")
    changes = [_with_original(base, e) for e in code_edits]
    diff = edit_rules.unified_diff(file.path, base, suggested)
    action = AgentAction(
        run_id=ctx.run_id,
        user_id=ctx.owner.id,
        project_id=ctx.project.id,
        file_id=record.id,
        file_path=file.path,
        kind="code_change",
        group_id=uuid.uuid4(),
        confidence=args.confidence,
        risk=args.risk,
        status=AgentActionStatus.PENDING,
        summary=args.summary.strip(),
        explanation=args.explanation.strip(),
        changes=[c.model_dump() for c in changes],
        diff=diff,
        base_content_hash=edit_rules.text_hash(base),
        result={},
    )
    ctx.session.add(action)
    ctx.session.flush()
    ctx.actions.append(action)
    changed = sum(1 for line in diff.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---")))
    unsaved = file.path == ctx.request.file_path and ctx.request.code is not None and ctx.request.code != base
    note = "Stored as a proposal; nothing was changed. The developer reviews it and may apply or reject it."
    if unsaved:
        note += " The editor has unsaved changes to this file; the proposal is based on the saved version."
    return (
        FixOut(
            action_id=str(action.id), file_path=file.path, changed_lines=changed, status="pending", note=note
        ),
        f"Proposed a change to {file.path} ({changed} changed line(s)); waiting for your review",
    )


def _validated_change(
    ctx: ToolContext, raw_path: str, edits: list[ModelLineEdit]
) -> tuple[ProjectFile, str, str, list[CodeEdit]]:
    """(stored file, original, changed content, edits) for whole-line edits of one saved file."""
    file = ctx.file(raw_path)
    record = ctx.stored(file)
    base = record.content or ""
    if len(base) > 100_000:
        raise ToolError(
            f"{file.path}: changes can only be proposed for files under 100,000 characters.",
            code="file_too_large",
        )
    try:
        code_edits = edit_rules.validate_edits(
            file.path, base, edit_rules.line_edits_to_code_edits(file.path, base, edits)
        )
        suggested = edit_rules.apply_edits(base, code_edits)
        edit_rules.check_change_is_safe(base, suggested)
    except edit_rules.InvalidEditError as exc:
        raise ToolError(
            f"{file.path}: the proposed edits are invalid: {exc.message}", code="invalid_edit"
        ) from None
    if suggested == base:
        raise ToolError(f"{file.path}: the proposed edits do not change the file.", code="no_change")
    return record, base, suggested, code_edits


def _changed_lines(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---")))


def propose_changes(ctx: ToolContext, args: ChangesArgs) -> tuple[ChangesOut, str]:
    """A coordinated change to several saved files (e.g. a rename). Every file is validated before
    anything is stored; the proposals share one group and are approved or rejected together."""
    if ctx.project.root_path is not None:
        raise ToolError(
            "This project is linked to a server folder and cannot be edited.", code="project_read_only"
        )
    paths = [f.file_path for f in args.files]
    if len(set(paths)) != len(paths):
        raise ToolError("Each file may appear only once; put all its edits together.", code="duplicate_file")
    validated = [(_validated_change(ctx, f.file_path, f.edits)) for f in args.files]
    group_id = uuid.uuid4()
    actions: list[AgentAction] = []
    changed = 0
    for record, base, suggested, code_edits in validated:
        diff = edit_rules.unified_diff(record.path, base, suggested)
        changed += _changed_lines(diff)
        action = AgentAction(
            run_id=ctx.run_id,
            user_id=ctx.owner.id,
            project_id=ctx.project.id,
            file_id=record.id,
            file_path=record.path,
            kind="code_change",
            group_id=group_id,
            confidence=args.confidence,
            risk=args.risk,
            status=AgentActionStatus.PENDING,
            summary=args.summary.strip(),
            explanation=args.explanation.strip(),
            changes=[_with_original(base, e).model_dump() for e in code_edits],
            diff=diff,
            base_content_hash=edit_rules.text_hash(base),
            result={},
        )
        ctx.session.add(action)
        actions.append(action)
    ctx.session.flush()
    ctx.actions.extend(actions)
    return (
        ChangesOut(
            group_id=str(group_id),
            action_ids=[str(a.id) for a in actions],
            files=[a.file_path for a in actions],
            changed_lines=changed,
            status="pending",
            note="Stored as ONE proposal covering every file; nothing was changed. The developer approves or "
            "rejects all files together.",
        ),
        f"Proposed a change to {len(actions)} file(s) ({changed} changed line(s)); waiting for your review",
    )


def propose_new_file(ctx: ToolContext, args: NewFileArgs) -> tuple[ChangesOut, str]:
    """A new project file (e.g. tests or documentation) for the developer to review; nothing is written."""
    if ctx.project.root_path is not None:
        raise ToolError(
            "This project is linked to a server folder and cannot be edited.", code="project_read_only"
        )
    try:
        path = _path_adapter.validate_python(args.file_path)
    except ValidationError:
        raise ToolError(
            f"{args.file_path!r} is not a valid project file path.", code="invalid_path"
        ) from None
    if not is_searchable(path) or is_secret_path(path):
        raise ToolError(
            f"{path} is inside an ignored folder or is a credentials file; it cannot be proposed.",
            code="path_not_allowed",
        )
    if path in ctx.index.files or FileRepository(ctx.session).get_by_path(ctx.project.id, path) is not None:
        raise ToolError(f"{path} already exists; propose edits to it instead.", code="file_exists")
    content = args.content if args.content.endswith("\n") else args.content + "\n"
    if len(content.encode("utf-8")) > ctx.settings.max_source_bytes:
        raise ToolError("The new file is larger than the source size limit.", code="file_too_large")
    diff = edit_rules.unified_diff(path, "", content)
    lines = content.count("\n")
    action = AgentAction(
        run_id=ctx.run_id,
        user_id=ctx.owner.id,
        project_id=ctx.project.id,
        file_id=None,
        file_path=path,
        kind="create_file",
        group_id=uuid.uuid4(),
        confidence=args.confidence,
        status=AgentActionStatus.PENDING,
        summary=args.summary.strip(),
        explanation=args.explanation.strip(),
        changes=[
            ProposedChange(
                file_path=path,
                start_line=1,
                start_column=1,
                end_line=1,
                end_column=1,
                original_text="",
                replacement_text=content,
            ).model_dump()
        ],
        diff=diff,
        base_content_hash=edit_rules.text_hash(""),
        result={},
    )
    ctx.session.add(action)
    ctx.session.flush()
    ctx.actions.append(action)
    return (
        ChangesOut(
            group_id=str(action.group_id),
            action_ids=[str(action.id)],
            files=[path],
            changed_lines=lines,
            status="pending",
            note="Stored as a proposal for a NEW file; nothing was written. The developer reviews it and may "
            "create it or reject it.",
        ),
        f"Proposed a new file {path} ({lines} line(s)); waiting for your review",
    )


def original_text(base: str, edit: CodeEdit) -> str:
    """The exact text an edit replaces (positions were validated against ``base``)."""
    lines = edit_rules.line_table(base)
    return base[
        lines.offset(edit.start_line, edit.start_column) : lines.offset(edit.end_line, edit.end_column)
    ]


def _with_original(base: str, edit: CodeEdit) -> ProposedChange:
    return ProposedChange(
        file_path=edit.file_path,
        start_line=edit.start_line,
        start_column=edit.start_column,
        end_line=edit.end_line,
        end_column=edit.end_column,
        original_text=original_text(base, edit),
        replacement_text=edit.replacement_text,
    )


# --- registry ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: ToolPermission
    args: type[_Args]
    output: type[BaseModel]
    handler: Callable[[ToolContext, Any], tuple[BaseModel, str]]
    # Soft per-call time budget: checked after the call (tools are bounded by their own limits).
    timeout_seconds: float = 20.0
    max_output_chars: int = 8000
    progress: str = ""

    def run(self, ctx: ToolContext, args: _Args) -> tuple[BaseModel, str, int]:
        started = time.perf_counter()
        output, summary = self.handler(ctx, args)
        if not isinstance(output, self.output):
            raise ToolError("The tool returned an unexpected result.", code="tool_output_invalid")
        return output, summary, round((time.perf_counter() - started) * 1000)


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "get_diagnostics",
            "The problems (deterministic diagnostics) currently shown for the open file, with their ids.",
            ToolPermission.READ_ONLY,
            NoArgs,
            DiagnosticsOut,
            get_diagnostics,
            progress="Reading the problems shown in the editor…",
        ),
        ToolSpec(
            "analyze_code",
            "Run CodeWalk's deterministic analyzers (syntax, lint, types) on a project file. "
            "Never executes it.",
            ToolPermission.READ_ONLY,
            FileArgs,
            DiagnosticsOut,
            analyze_code,
            progress="Analyzing code…",
        ),
        ToolSpec(
            "search_project",
            "Deterministic project search over symbols, file names and paths, imports, identifiers, "
            "and text.",
            ToolPermission.READ_ONLY,
            SearchArgs,
            SearchOut,
            search_project,
            progress="Searching the project…",
        ),
        ToolSpec(
            "semantic_search_project",
            "Search by meaning: hybrid of deterministic search and code-embedding similarity. Falls back to "
            "deterministic search (and says so) when semantic retrieval is unavailable.",
            ToolPermission.READ_ONLY,
            SearchArgs,
            SearchOut,
            semantic_search_project,
            progress="Retrieving semantically related code…",
        ),
        ToolSpec(
            "get_project_context",
            "Related code for a file and line: containing symbol, definitions of names in its problems, "
            "imports, importers, and similar code.",
            ToolPermission.READ_ONLY,
            ContextArgs,
            ContextOut,
            get_project_context,
            progress="Collecting project context…",
        ),
        ToolSpec(
            "get_file_content",
            f"Read lines of a project file (at most {MAX_FILE_LINES} lines per call). The open file returns "
            "the editor's current, possibly unsaved, content.",
            ToolPermission.READ_ONLY,
            FileContentArgs,
            FileContentOut,
            get_file_content,
            progress="Reading a file…",
        ),
        ToolSpec(
            "get_symbol",
            "Find the definition(s) of a function, class, method, or other symbol by name.",
            ToolPermission.READ_ONLY,
            SymbolArgs,
            SymbolOut,
            get_symbol,
            progress="Looking up a symbol…",
        ),
        ToolSpec(
            "explain_error",
            "Collect the evidence needed to explain one problem from get_diagnostics: the problem, the code "
            "around it, the containing symbol, and related definitions.",
            ToolPermission.READ_ONLY,
            ExplainArgs,
            ExplainOut,
            explain_error,
            progress="Analyzing the problem…",
        ),
        ToolSpec(
            "get_architecture",
            "Deterministic architecture summary of the project: components (top folders), file roles, import "
            "links between components, entry points, HTTP routes, database models.",
            ToolPermission.READ_ONLY,
            NoArgs,
            insights.ArchitectureReport,
            get_architecture,
            max_output_chars=12000,
            progress="Summarizing the project architecture…",
        ),
        ToolSpec(
            "analyze_impact",
            "What may break if a file (or one symbol in it) changes: dependents through resolved imports "
            "(confirmed), name-only matches (possible), related tests and HTTP routes. No call graph.",
            ToolPermission.READ_ONLY,
            ImpactArgs,
            insights.ImpactReport,
            analyze_impact,
            max_output_chars=12000,
            progress="Analyzing the impact of a change…",
        ),
        ToolSpec(
            "find_references",
            "Definitions of a name and the files that use it, labelled confirmed (connected by an import) or "
            "possible (same name only).",
            ToolPermission.READ_ONLY,
            NameArgs,
            insights.ReferenceReport,
            find_references,
            progress="Finding references…",
        ),
        ToolSpec(
            "find_related_tests",
            "Test files that import a file (confirmed) or are named after it (possible). Read them to learn "
            "the project's test framework, fixtures, and conventions before proposing tests.",
            ToolPermission.READ_ONLY,
            FileArgs,
            TestsOut,
            find_related_tests,
            progress="Looking for related tests…",
        ),
        ToolSpec(
            "record_finding",
            f"Record one code-review finding in this run's report (at most {MAX_FINDINGS}). It must point at "
            "real lines you have read, quote the evidence, and state your confidence. Does not change files. "
            "Report only issues the code shows; do not present speculation as fact.",
            ToolPermission.READ_ONLY,
            FindingArgs,
            FindingOut,
            record_finding,
            progress="Recording a review finding…",
        ),
        ToolSpec(
            "get_project_activity",
            "Recent activity in this project, newest first: files created/edited/restored/deleted, analyses, "
            "AI explanations and fixes, agent runs and applied/rejected proposals. Use it only for questions "
            "about what was done or changed (e.g. 'what have we done', 'what changed yesterday').",
            ToolPermission.READ_ONLY,
            ActivityArgs,
            ActivityOut,
            get_project_activity,
            progress="Reading recent project activity…",
        ),
        ToolSpec(
            "propose_fix",
            "Propose a change to ONE saved project file as whole-line edits "
            "(start_line..end_line replaced by "
            "`replacement`, using the saved file's line numbers). It is stored for the developer to review "
            "and is NOT applied. Read the file first.",
            ToolPermission.PROPOSED_CHANGE,
            FixArgs,
            FixOut,
            propose_fix,
            progress="Preparing a proposed change…",
        ),
        ToolSpec(
            "propose_changes",
            f"Propose ONE coordinated change across up to {MAX_PROPOSAL_FILES} saved files (e.g. a rename "
            "or a refactoring), each as whole-line edits like propose_fix. All files are validated first; "
            "the developer approves or rejects them together. Use analyze_impact first to find every "
            "affected file.",
            ToolPermission.PROPOSED_CHANGE,
            ChangesArgs,
            ChangesOut,
            propose_changes,
            progress="Preparing a multi-file change…",
        ),
        ToolSpec(
            "propose_new_file",
            "Propose a NEW project file (tests, documentation) with its full content. It is stored for "
            "review and NOT written. Match the project's existing conventions (read similar files first).",
            ToolPermission.PROPOSED_CHANGE,
            NewFileArgs,
            ChangesOut,
            propose_new_file,
            progress="Preparing a new file…",
        ),
    )
}


def tool_catalog() -> list[dict[str, Any]]:
    """What the model is told about each tool: name, permission, description, and argument schema."""
    return [
        {
            "name": spec.name,
            "permission": spec.permission.value,
            "description": spec.description,
            "arguments": spec.args.model_json_schema(),
        }
        for spec in TOOLS.values()
    ]
