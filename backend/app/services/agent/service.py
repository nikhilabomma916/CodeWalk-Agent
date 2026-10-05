"""Agent orchestration (Module 11): a bounded, policy-checked tool loop over the AI provider.

Flow per run:
  request -> ownership + validation -> [model step -> policy -> tool -> result as data]* -> answer
Each model step is one validated JSON decision (call one tool, or answer). Every
tool call is authorized by ``ToolPolicy`` and executed against the signed-in
user's project only. Limits: steps, wall-clock time, kept context, proposals,
repeated calls, and consecutive failures; reaching one ends the run safely
(``limit_reached``). Provider failures end it as ``failed``. Runs, progress events,
and tool-call metadata are stored; model reasoning is never requested or stored.

The service is synchronous and returns the finished run. Events are produced in
order through ``_emit`` so a streaming transport can be added without changing
the loop.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.core.metrics import METRICS
from app.core.rate_limit import RateLimiter
from app.db.models import (
    ActivityType,
    AgentAction,
    AgentRun,
    AgentRunStatus,
    ProjectOrigin,
    User,
)
from app.schemas.agent import (
    AgentActionOut,
    AgentContextInfo,
    AgentEvent,
    AgentEventType,
    AgentMode,
    AgentRunError,
    AgentRunOut,
    AgentRunRequest,
    AgentStatusResponse,
    AgentToolInfo,
    AgentUsage,
    ReviewFinding,
    ToolCallRecord,
    ToolPermission,
)
from app.services.activity import ActivityRecorder
from app.services.agent import prompts
from app.services.agent.policy import ToolDeniedError, ToolPolicy
from app.services.agent.tools import TOOLS, ToolContext, ToolError, ToolSpec
from app.services.ai.base import (
    AIDisabledError,
    AIError,
    AIMalformedResponseError,
    AINotConfiguredError,
    AIProvider,
)
from app.services.ai.service import AIService
from app.services.analysis.engine import AnalysisEngine
from app.services.memory import MemoryService
from app.services.project_search.context import ProjectContextBuilder
from app.services.project_search.index import ProjectIndex
from app.services.project_search.service import ProjectSearchService

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 20_000
MAX_STATUS_CHARS = 160
MAX_ARGUMENT_CHARS = 200
TRUNCATION_NOTE = "\n[... output truncated to the per-tool limit ...]"


class AgentRunLimitError(AppError):
    status_code = 429
    code = "too_many_agent_runs"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many agent requests. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


class InvalidAgentRequestError(AppError):
    status_code = 422
    code = "invalid_agent_request"


def _now() -> datetime:
    return datetime.now(UTC)


def _status_text(text: str) -> str:
    line = " ".join(text.split())
    return line[:MAX_STATUS_CHARS] if line else "Working…"


def _safe_arguments(spec: ToolSpec | None, arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as recorded in history: bounded, and never proposed file contents."""
    if spec is not None and spec.permission is ToolPermission.PROPOSED_CHANGE:
        edits = arguments.get("edits")
        return {
            "file_path": str(arguments.get("file_path", ""))[:MAX_ARGUMENT_CHARS],
            "edits": len(edits) if isinstance(edits, list) else 0,
        }
    safe: dict[str, Any] = {}
    for key, value in list(arguments.items())[:10]:
        if isinstance(value, str):
            safe[str(key)[:50]] = value[:MAX_ARGUMENT_CHARS]
        elif isinstance(value, int | float | bool) or value is None:
            safe[str(key)[:50]] = value
        else:
            safe[str(key)[:50]] = "…"
    return safe


class AgentService:
    """Per-request agent operations for the signed-in user."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        owner: User,
        ai: AIService,
        limiter: RateLimiter,
        search: ProjectSearchService,
        context_builder: ProjectContextBuilder,
        engine: AnalysisEngine,
    ) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.ai = ai
        self.limiter = limiter
        self.search = search
        self.context_builder = context_builder
        self.engine = engine

    # --- status ---------------------------------------------------------------------------

    def status(self) -> AgentStatusResponse:
        ai_status = self.ai.status()
        return AgentStatusResponse(
            available=ai_status.available,
            detail=None if ai_status.available else (ai_status.detail or "AI assistance is not available."),
            tools=[
                AgentToolInfo(name=s.name, description=s.description, permission=s.permission)
                for s in TOOLS.values()
            ],
            max_steps=self.settings.agent_max_steps,
            max_actions=self.settings.agent_max_actions,
            max_tool_calls=self.settings.agent_max_tool_calls,
            modes=[m.value for m in AgentMode],
        )

    def _provider(self) -> AIProvider:
        """The configured provider, without consuming the per-request AI limit (agent runs have their own)."""
        if not self.settings.ai_enabled:
            raise AIDisabledError()
        provider = self.ai.provider
        if provider is None:
            raise AINotConfiguredError(self.ai.provider_problem or "No AI provider is configured.")
        state = provider.status()
        if not state.configured:
            raise AINotConfiguredError(state.detail or "The AI provider is not configured.")
        return provider

    # --- validation -----------------------------------------------------------------------

    def _validate(self, request: AgentRunRequest, index: ProjectIndex) -> None:
        if request.file_path is not None and request.file_path not in index.files:
            raise NotFoundError(
                "The open file is not part of this project (or cannot be used as context).",
                code="file_not_found",
            )
        if request.code is None:
            return
        if len(request.code.encode("utf-8")) > self.settings.max_source_bytes:
            raise AppError(
                f"The open file is larger than {self.settings.max_source_bytes} bytes.",
                code="source_too_large",
                status_code=413,
            )
        line_count = max(len(request.code.splitlines()), 1)
        if request.selection is not None and request.selection.end_line > line_count + 1:
            raise InvalidAgentRequestError(
                f"The selection ends at line {request.selection.end_line}, "
                f"but the file has {line_count} lines."
            )
        for diagnostic in request.diagnostics:
            if diagnostic.line > line_count or diagnostic.end_line > line_count + 1:
                raise InvalidAgentRequestError(
                    f"Problem {diagnostic.id} points at line {diagnostic.line}, "
                    f"but the file has {line_count} lines."
                )

    # --- run ------------------------------------------------------------------------------

    def run(self, request: AgentRunRequest) -> AgentRunOut:
        provider = self._provider()
        key = f"agent:{self.owner.id}"
        if (retry_after := self.limiter.retry_after(key)) is not None:
            audit("rate_limited", level=logging.WARNING, scope="agent", user=self.owner.id)
            raise AgentRunLimitError(retry_after)
        project, index = self.search.project_index(request.project_id)  # 404 for other users' projects
        self._validate(request, index)
        # Every accepted run counts toward the limit. Checked again atomically here: simultaneous
        # requests may all have passed the early check above before any of them was recorded.
        if (retry_after := self.limiter.acquire(key)) is not None:
            audit("rate_limited", level=logging.WARNING, scope="agent", user=self.owner.id)
            raise AgentRunLimitError(retry_after)

        started = time.perf_counter()
        deadline = started + self.settings.agent_timeout_seconds
        run = AgentRun(
            id=uuid.uuid4(),
            user_id=self.owner.id,
            project_id=project.id,
            status=AgentRunStatus.COMPLETED,
            message=request.message.strip(),
            file_path=request.file_path,
            provider=provider.name,
            model=provider.model,
            events=[],
            tool_calls=[],
            warnings=[],
            duration_ms=0,
            mode=request.mode.value,
            findings=[],
            usage={},
        )
        self.session.add(run)
        self.session.flush()
        logger.info(
            "Agent run %s started (project %s, file %s)", run.id, project.id, request.file_path or "-"
        )

        events: list[AgentEvent] = []
        calls: list[ToolCallRecord] = []
        warnings: list[str] = []
        turns: list[prompts.ToolTurn] = []
        # Uploaded projects (Module 18) are analyzed read-only: the agent answers but proposes nothing.
        read_only = project.origin is ProjectOrigin.UPLOAD
        policy = ToolPolicy(
            max_actions=0 if read_only else self.settings.agent_max_actions,
            max_tool_calls=self.settings.agent_max_tool_calls,
            read_only=read_only,
        )
        # The developer's saved notes for this project (ownership was checked above).
        memory = MemoryService(self.session, self.settings, self.owner).for_prompt(project.id)
        notes = [(m.kind.value, m.text) for m in memory]
        usage = AgentUsage()
        ctx = ToolContext(
            session=self.session,
            settings=self.settings,
            owner=self.owner,
            project=project,
            index=index,
            search=self.search,
            context_builder=self.context_builder,
            engine=self.engine,
            request=request,
            run_id=run.id,
        )

        def emit(kind: AgentEventType, message: str, **extra: Any) -> None:
            tool = extra.pop("tool", None)
            events.append(AgentEvent(type=kind, message=message, at=_now(), tool=tool, data=extra))

        emit(AgentEventType.STARTED, "Agent started")
        system = prompts.system_prompt(request.mode)
        max_steps = self.settings.agent_max_steps
        answer: str | None = None
        status = AgentRunStatus.COMPLETED
        error: AgentRunError | None = None

        for step in range(1, max_steps + 1):
            remaining = deadline - time.perf_counter()
            if remaining <= 1:
                status = AgentRunStatus.LIMIT_REACHED
                warnings.append("The agent stopped at its time limit before answering.")
                emit(AgentEventType.LIMIT_REACHED, "Stopped: time limit reached")
                break
            kept = sum(len(t.content) for t in turns)
            tokens = usage.input_tokens + usage.output_tokens
            over_budget = tokens >= self.settings.agent_max_tokens_per_run
            answer_now = (
                step == max_steps
                or kept >= self.settings.agent_max_context_chars
                or policy.stuck
                or policy.out_of_calls
                or over_budget
            )
            user = prompts.user_prompt(
                request,
                project.name,
                turns,
                steps_left=max_steps - step,
                actions_left=policy.max_actions - policy.actions,
                answer_now=answer_now,
                notes=notes,
            )
            usage.largest_prompt_chars = max(usage.largest_prompt_chars, len(system) + len(user))
            try:
                decision, result = self.ai.run(
                    provider, system, user, prompts.ModelAgentStep, timeout_seconds=remaining
                )
                usage.provider_calls += 1
                usage.input_tokens += int(result.usage.get("input_tokens", 0) or 0)
                usage.output_tokens += int(result.usage.get("output_tokens", 0) or 0)
            except AIError as exc:
                usage.provider_calls += 1
                status = AgentRunStatus.FAILED
                error = AgentRunError(code=exc.code, message=exc.message)
                emit(AgentEventType.FAILED, exc.message)
                logger.warning("Agent run %s: provider error %s at step %d", run.id, exc.code, step)
                break
            emit(AgentEventType.PLANNING, _status_text(decision.status_message))

            if decision.action == "answer":
                text = (decision.answer or "").strip()
                if not text:
                    status = AgentRunStatus.FAILED
                    malformed = AIMalformedResponseError("The agent returned an empty answer.")
                    error = AgentRunError(code=malformed.code, message=malformed.message)
                    emit(AgentEventType.FAILED, malformed.message)
                    break
                answer = text[:MAX_ANSWER_CHARS]
                emit(AgentEventType.RESPONSE, "Prepared a response")
                break
            if answer_now:
                status = AgentRunStatus.LIMIT_REACHED
                reason = (
                    "repeated failed tool calls"
                    if policy.stuck
                    else "the context limit"
                    if kept >= self.settings.agent_max_context_chars
                    else "the tool-call limit"
                    if policy.out_of_calls
                    else "the token budget"
                    if over_budget
                    else "the step limit"
                )
                warnings.append(f"The agent stopped at {reason} before answering.")
                emit(AgentEventType.LIMIT_REACHED, f"Stopped: {reason}")
                break
            self._call_tool(step, decision, ctx, policy, turns, calls, warnings, emit)

        run.status = status
        run.answer = answer
        run.error_code = error.code if error else None
        run.error_message = error.message if error else None
        emit(
            AgentEventType.COMPLETED if status is not AgentRunStatus.FAILED else AgentEventType.FAILED,
            "Completed"
            if status is AgentRunStatus.COMPLETED
            else ("Stopped" if status is AgentRunStatus.LIMIT_REACHED else "Failed"),
        )
        run.events = [e.model_dump(mode="json") for e in events]
        run.tool_calls = [c.model_dump(mode="json") for c in calls]
        run.warnings = warnings
        usage.tool_calls = len(calls)
        run.usage = {**usage.model_dump(), "files_inspected": ctx.inspected[:100], "memory_items": len(notes)}
        run.findings = list(ctx.findings)
        run.duration_ms = round((time.perf_counter() - started) * 1000)
        run.completed_at = _now()
        METRICS.observe("agent_run", time.perf_counter() - started, status.value)
        ActivityRecorder(self.session, self.owner).record(
            ActivityType.AGENT_RUN,
            project,
            file_path=request.file_path,
            details={
                "run_id": str(run.id),
                "status": status.value,
                "tool_calls": len(calls),
                "proposed_changes": len(ctx.actions),
                "mode": request.mode.value,
                "findings": len(ctx.findings),
            },
        )
        self.session.commit()
        logger.info(
            "Agent run %s %s (mode %s): %d tool call(s), %d proposal(s), %d finding(s), %d provider call(s), "
            "%d tokens, %d ms",
            run.id,
            status.value,
            request.mode.value,
            len(calls),
            len(ctx.actions),
            len(ctx.findings),
            usage.provider_calls,
            usage.input_tokens + usage.output_tokens,
            run.duration_ms,
        )
        return self.get_run(run.id)

    def _call_tool(
        self,
        step: int,
        decision: prompts.ModelAgentStep,
        ctx: ToolContext,
        policy: ToolPolicy,
        turns: list[prompts.ToolTurn],
        calls: list[ToolCallRecord],
        warnings: list[str],
        emit: Any,
    ) -> None:
        name = (decision.tool or "")[:80]

        def record(
            status: str,
            summary: str,
            spec: ToolSpec | None,
            arguments: dict[str, Any],
            ms: int = 0,
            code: str | None = None,
        ) -> None:
            calls.append(
                ToolCallRecord(
                    index=len(calls) + 1,
                    tool=name or "?",
                    permission=spec.permission if spec else None,
                    arguments=_safe_arguments(spec, arguments),
                    status=status,
                    summary=summary,
                    duration_ms=ms,
                    error_code=code,
                )
            )

        def denied(spec: ToolSpec | None, arguments: dict[str, Any], exc: ToolDeniedError) -> None:
            policy.failed()
            turns.append(prompts.ToolTurn(step, name or "?", "denied", exc.message))
            record("denied", exc.message, spec, arguments, code=exc.code)
            emit(AgentEventType.TOOL_DENIED, f"Not allowed: {exc.message}", tool=name or None, code=exc.code)
            audit(
                "agent_tool_denied",
                level=logging.WARNING,
                user=self.owner.id,
                project=ctx.project.id,
                run=ctx.run_id,
                tool=name or "-",
                reason=exc.code,
            )

        def failed(
            spec: ToolSpec | None, arguments: dict[str, Any], code: str, message: str, key: str | None
        ) -> None:
            policy.failed(key)
            turns.append(prompts.ToolTurn(step, name or "?", "error", message))
            record("error", message, spec, arguments, code=code)
            emit(AgentEventType.TOOL_FAILED, message, tool=name or None, code=code)

        try:
            spec = policy.resolve(name)
        except ToolDeniedError as exc:
            denied(None, {}, exc)
            return
        try:
            raw = json.loads(decision.arguments_json or "{}")
        except json.JSONDecodeError:
            failed(spec, {}, "invalid_arguments", "The arguments were not valid JSON.", None)
            return
        if not isinstance(raw, dict):
            failed(spec, {}, "invalid_arguments", "The arguments must be a JSON object.", None)
            return
        try:
            args = spec.args.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
            )
            failed(spec, raw, "invalid_arguments", f"Invalid arguments for {spec.name}: {problems}", None)
            return
        arguments = args.model_dump(mode="json")
        try:
            key = policy.check(spec, arguments)
        except ToolDeniedError as exc:
            denied(spec, arguments, exc)
            return

        emit(AgentEventType.TOOL_STARTED, spec.progress or f"Running {spec.name}…", tool=spec.name)
        started = time.perf_counter()
        try:
            output, summary, ms = spec.run(ctx, args)
        except ToolError as exc:
            failed(spec, arguments, exc.code, exc.message, key)
            return
        except AppError as exc:  # e.g. file not found, source too large, retrieval failure
            failed(spec, arguments, exc.code, exc.message, key)
            return
        except Exception:
            logger.exception("Agent tool %s failed (run %s)", spec.name, ctx.run_id)
            failed(spec, arguments, "tool_failed", f"{spec.name} failed unexpectedly.", key)
            return

        content = output.model_dump_json()
        if len(content) > spec.max_output_chars:
            content = content[: spec.max_output_chars] + TRUNCATION_NOTE
        policy.succeeded(key, spec)
        turns.append(prompts.ToolTurn(step, spec.name, "ok", content))
        record("ok", summary, spec, arguments, ms)
        emit(AgentEventType.TOOL_COMPLETED, summary, tool=spec.name, duration_ms=ms)
        if ms > spec.timeout_seconds * 1000:
            warnings.append(
                f"{spec.name} took {ms / 1000:.1f}s, longer than its {spec.timeout_seconds:.0f}s budget."
            )
        logger.info(
            "Agent run %s: %s ok in %d ms",
            ctx.run_id,
            spec.name,
            round((time.perf_counter() - started) * 1000),
        )
        if spec.permission is ToolPermission.PROPOSED_CHANGE and ctx.actions:
            action = ctx.actions[-1]
            emit(
                AgentEventType.ACTION_PROPOSED,
                f"Proposed a change to {action.file_path}",
                action_id=str(action.id),
            )
            audit(
                "agent_action_proposed",
                user=self.owner.id,
                project=ctx.project.id,
                run=ctx.run_id,
                action=action.id,
            )

    # --- reading runs ---------------------------------------------------------------------

    def _owned_run(self, run_id: uuid.UUID) -> AgentRun:
        run = self.session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == self.owner.id)
        )
        if run is None:
            raise NotFoundError("Agent run not found.", code="agent_run_not_found")
        return run

    def get_run(self, run_id: uuid.UUID) -> AgentRunOut:
        run = self._owned_run(run_id)
        actions = self.session.scalars(
            select(AgentAction).where(AgentAction.run_id == run.id).order_by(AgentAction.created_at)
        ).all()
        group_sizes: dict[Any, int] = {}
        for a in actions:
            group_sizes[a.group_id] = group_sizes.get(a.group_id, 0) + 1
        usage = dict(run.usage or {})
        error = (
            AgentRunError(code=run.error_code, message=run.error_message or "") if run.error_code else None
        )
        return AgentRunOut(
            id=run.id,
            project_id=run.project_id,
            status=run.status.value,
            message=run.message,
            file_path=run.file_path,
            answer=run.answer,
            provider=run.provider,
            model=run.model,
            error=error,
            events=[AgentEvent.model_validate(e) for e in run.events],
            tool_calls=[ToolCallRecord.model_validate(c) for c in run.tool_calls],
            mode=run.mode,
            actions=[action_out(a, group_sizes.get(a.group_id, 1) if a.group_id else 1) for a in actions],
            findings=[ReviewFinding.model_validate(f) for f in run.findings or []],
            usage=AgentUsage.model_validate({k: v for k, v in usage.items() if k in AgentUsage.model_fields}),
            context=AgentContextInfo(
                files_inspected=list(usage.get("files_inspected", [])),
                memory_items=int(usage.get("memory_items", 0)),
            ),
            warnings=list(run.warnings),
            duration_ms=run.duration_ms,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    def events(self, run_id: uuid.UUID) -> list[AgentEvent]:
        return [AgentEvent.model_validate(e) for e in self._owned_run(run_id).events]


def action_out(action: AgentAction, group_size: int = 1) -> AgentActionOut:
    return AgentActionOut(
        id=action.id,
        run_id=action.run_id,
        kind=action.kind,
        group_id=action.group_id,
        group_size=group_size,
        confidence=action.confidence,
        risk=action.risk,
        status=action.status.value,
        file_path=action.file_path,
        summary=action.summary,
        explanation=action.explanation,
        changes=action.changes,  # type: ignore[arg-type]
        diff=action.diff,
        base_content_hash=action.base_content_hash,
        created_at=action.created_at,
        decided_at=action.decided_at,
        result=action.result,
    )
