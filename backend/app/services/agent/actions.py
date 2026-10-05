"""Approving or rejecting an agent's proposed change: the only path from a proposal to a file write.

Approval re-checks everything at decision time, never trusting the proposal or the client:
1. the action belongs to the signed-in user and is still pending (its row is locked);
2. its project is the user's and is editable (not folder-linked);
3. the file still exists at the same path (its row is locked, so concurrent approvals of different
   proposals for one file cannot both apply against the same original content);
4. the file's content hash equals the hash the proposal was computed against, and every
   change's original text is still exactly at its range (otherwise: ``stale``, not applied);
5. the result is bounded (size, changed lines).
The file is then saved through ``FileService`` (new version, deterministic re-analysis,
history), and the resulting diagnostics are returned. Rejection changes no file.

Module 17 adds:
- ``create_file`` proposals (tests, documentation): applied only if the path is still free and allowed;
- groups: proposals made by one tool call (a multi-file change) are decided together. Every file is
  re-validated first; if any one is stale, nothing is applied and the whole group becomes stale. The
  saves are committed in one transaction. A grouped proposal cannot be decided on its own.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import (
    ActivityType,
    AgentAction,
    AgentActionStatus,
    FileVersion,
    Project,
    ProjectFile,
    User,
)
from app.repositories.analyses import DiagnosticRepository
from app.repositories.files import FileRepository
from app.schemas.agent import (
    ActionDecisionResponse,
    AgentActionOut,
    AppliedFile,
    AppliedGroupFile,
    GroupDecisionResponse,
    ProposedChange,
    UndoResponse,
)
from app.schemas.ai import CodeEdit
from app.schemas.analysis import StoredDiagnostic
from app.schemas.projects import FileCreate, FileUpdate
from app.services.activity import ActivityRecorder
from app.services.agent.service import action_out
from app.services.ai import edits as edit_rules
from app.services.files import FileService, ProjectReadOnlyError
from app.services.project_intelligence.scanner import is_secret_path
from app.services.project_search.index import is_searchable
from app.services.projects import ProjectService

logger = logging.getLogger(__name__)


class ActionNotPendingError(ConflictError):
    code = "action_not_pending"


class GroupDecisionRequiredError(ConflictError):
    code = "group_decision_required"

    def __init__(self, size: int) -> None:
        super().__init__(
            f"This proposal is one of {size} files changed together; approve or reject the whole group."
        )


class StaleActionError(AppError):
    status_code = 409
    code = "stale_action"


@dataclass
class _StaleError(Exception):
    reason: str
    message: str


class UndoNotPossibleError(ConflictError):
    code = "undo_not_possible"


@dataclass
class _Prepared:
    action: AgentAction
    record: ProjectFile | None  # None for create_file
    content: str


class AgentActionService:
    def __init__(self, session: Session, owner: User, files: FileService, projects: ProjectService) -> None:
        self.session = session
        self.owner = owner
        self.files = files
        self.projects = projects
        # Diagnostics of each file saved by the current decision, by action id.
        self._diagnostics: dict[uuid.UUID, list[dict[str, object]]] = {}

    # --- lookups ---------------------------------------------------------------------------------

    def _owned(self, action_id: uuid.UUID) -> AgentAction:
        # Lock the row for this decision: concurrent approve/reject requests for the same proposal
        # run one after another, so only the first sees it pending (the rest get action_not_pending).
        action = self.session.scalar(
            select(AgentAction)
            .where(AgentAction.id == action_id, AgentAction.user_id == self.owner.id)
            .with_for_update()
        )
        if action is None:
            audit("agent_action_not_found", level=logging.WARNING, user=self.owner.id, action=action_id)
            raise NotFoundError("Proposed change not found.", code="agent_action_not_found")
        self.projects.get(action.project_id)  # ownership of the project, re-checked now
        return action

    def _group_size(self, action: AgentAction) -> int:
        if action.group_id is None:
            return 1
        return int(
            self.session.scalar(
                select(func.count()).select_from(AgentAction).where(AgentAction.group_id == action.group_id)
            )
            or 1
        )

    def _owned_group(self, group_id: uuid.UUID) -> list[AgentAction]:
        actions = list(
            self.session.scalars(
                select(AgentAction)
                .where(AgentAction.group_id == group_id, AgentAction.user_id == self.owner.id)
                .order_by(AgentAction.id)
                .with_for_update()
            ).all()
        )
        if not actions:
            audit("agent_group_not_found", level=logging.WARNING, user=self.owner.id, group=group_id)
            raise NotFoundError("Proposed change not found.", code="agent_action_not_found")
        for project_id in {a.project_id for a in actions}:
            self.projects.get(project_id)
        return actions

    @staticmethod
    def _pending(actions: list[AgentAction]) -> None:
        for action in actions:
            if action.status is not AgentActionStatus.PENDING:
                raise ActionNotPendingError(f"This proposed change was already {action.status.value}.")

    def _writable(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(project_id)
        if project.root_path is not None:
            raise ProjectReadOnlyError()
        return project

    # --- validation --------------------------------------------------------------------------------

    def _prepare(self, project: Project, action: AgentAction) -> _Prepared:
        """The content to save for one proposal, after re-checking it; raises ``_StaleError``."""
        changes = [ProposedChange.model_validate(c) for c in action.changes]
        if action.kind == "create_file":
            path = action.file_path
            if not is_searchable(path) or is_secret_path(path):
                raise _StaleError("path_not_allowed", f"{path} can no longer be created here.")
            if FileRepository(self.session).get_by_path(project.id, path) is not None:
                raise _StaleError(
                    "file_exists", f"{path} was created after this proposal; it was not overwritten."
                )
            return _Prepared(action, None, changes[0].replacement_text if changes else "")

        record = (
            FileRepository(self.session).get(project.id, action.file_id, for_update=True)
            if action.file_id is not None
            else None
        )
        if record is None:
            raise _StaleError("file_missing", f"{action.file_path} no longer exists.")
        if record.path != action.file_path:
            raise _StaleError("file_moved", f"{action.file_path} was renamed to {record.path}.")
        content = record.content
        if content is None or edit_rules.text_hash(content) != action.base_content_hash:
            raise _StaleError(
                "content_changed",
                f"{record.path} changed after this change was proposed, so it was not applied. "
                "Ask the agent again.",
            )
        edits = [
            CodeEdit(
                file_path=c.file_path,
                start_line=c.start_line,
                start_column=c.start_column,
                end_line=c.end_line,
                end_column=c.end_column,
                replacement_text=c.replacement_text,
            )
            for c in changes
        ]
        try:
            ordered = edit_rules.validate_edits(record.path, content, edits)
            lines = edit_rules.line_table(content)
            for change in changes:
                start = lines.offset(change.start_line, change.start_column)
                end = lines.offset(change.end_line, change.end_column)
                if content[start:end] != change.original_text:
                    raise _StaleError(
                        "original_mismatch", f"The code to replace in {record.path} is no longer there."
                    )
            updated = edit_rules.apply_edits(content, ordered)
            edit_rules.check_change_is_safe(content, updated)
        except edit_rules.InvalidEditError as exc:
            raise _StaleError(
                "invalid", f"The proposed change can no longer be applied: {exc.message}"
            ) from None
        return _Prepared(action, record, updated)

    def _mark_stale(
        self, actions: list[AgentAction], failed: AgentAction, stale: _StaleError
    ) -> StaleActionError:
        now = datetime.now(UTC)
        for action in actions:
            action.status = AgentActionStatus.STALE
            action.decided_at = now
            action.result = (
                {"reason": stale.reason}
                if action is failed
                else {"reason": "group_stale", "file": failed.file_path}
            )
        self.session.commit()
        audit(
            "agent_action_stale",
            level=logging.WARNING,
            user=self.owner.id,
            action=failed.id,
            group=failed.group_id,
            reason=stale.reason,
        )
        return StaleActionError(stale.message)

    # --- applying ----------------------------------------------------------------------------------

    def _apply(self, project: Project, prepared: _Prepared) -> AppliedGroupFile:
        """Save one prepared proposal without committing (the caller commits once)."""
        action = prepared.action
        action.status = AgentActionStatus.APPLIED
        action.decided_at = datetime.now(UTC)
        if prepared.record is None:
            saved, analysis = self.files.create(
                project.id, FileCreate(path=action.file_path, content=prepared.content), commit=False
            )
            action.file_id = saved.id
        else:
            saved, analysis = self.files.update(
                project.id, prepared.record.id, FileUpdate(content=prepared.content), commit=False
            )
        version = self.session.scalar(
            select(func.max(FileVersion.version)).where(FileVersion.file_id == saved.id)
        )
        diagnostics = (
            [
                StoredDiagnostic.model_validate(d).model_dump(mode="json")
                for d in DiagnosticRepository(self.session).list_by_analysis(analysis.id)
            ]
            if analysis is not None
            else []
        )
        action.result = {
            "version": version,
            "analysis_id": str(analysis.id) if analysis else None,
            "diagnostic_count": len(diagnostics),
            "created": prepared.record is None,
        }
        ActivityRecorder(self.session, self.owner).record(
            ActivityType.AGENT_ACTION_APPLIED,
            project,
            file=saved,
            analysis=analysis,
            details={
                "action_id": str(action.id),
                "run_id": str(action.run_id),
                "version": version,
                "kind": action.kind,
            },
        )
        self._diagnostics[action.id] = diagnostics
        return AppliedGroupFile(
            action_id=action.id,
            file=AppliedFile(
                file_id=saved.id,
                path=saved.path,
                content=saved.content or "",
                content_hash=saved.content_hash or "",
                version=version,
            ),
            diagnostic_count=len(diagnostics),
        )

    def _approve_all(self, actions: list[AgentAction]) -> list[AppliedGroupFile]:
        self._diagnostics.clear()
        self._pending(actions)
        project = self._writable(actions[0].project_id)
        # Lock files in a fixed order (by id) so two groups touching the same files cannot deadlock.
        prepared: list[_Prepared] = []
        for action in sorted(actions, key=lambda a: str(a.file_id or "")):
            try:
                prepared.append(self._prepare(project, action))
            except _StaleError as stale:
                raise self._mark_stale(actions, action, stale) from None
        applied = [self._apply(project, p) for p in sorted(prepared, key=lambda p: p.action.file_path)]
        self.session.commit()
        for item in applied:
            audit(
                "agent_action_applied",
                user=self.owner.id,
                project=project.id,
                action=item.action_id,
                version=item.file.version,
            )
        logger.info("Agent proposal applied to %d file(s) in project %s", len(applied), project.id)
        return applied

    # --- decisions ---------------------------------------------------------------------------------

    def approve(self, action_id: uuid.UUID) -> ActionDecisionResponse:
        action = self._owned(action_id)
        self._pending([action])
        size = self._group_size(action)
        if size > 1:
            raise GroupDecisionRequiredError(size)
        applied = self._approve_all([action])[0]
        return ActionDecisionResponse(
            action=action_out(action), file=applied.file, diagnostics=self._diagnostics[action.id]
        )

    # --- AI change history ------------------------------------------------------------------------

    def list_actions(
        self, project_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[AgentActionOut], int]:
        """The AI changes proposed in one of the developer's projects, newest first."""
        self.projects.get(project_id)  # 404 for another user's project
        query = select(AgentAction).where(
            AgentAction.project_id == project_id, AgentAction.user_id == self.owner.id
        )
        if status is not None:
            query = query.where(AgentAction.status == status)
        total = int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self.session.scalars(
            query.order_by(AgentAction.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return [action_out(row, self._group_size(row)) for row in rows], total

    def undo(self, action_id: uuid.UUID) -> UndoResponse:
        """Reverts an applied AI change if the file was not changed since: an edit restores the
        version before it (as a new version, so this can be undone too); a created file is deleted."""
        action = self._owned(action_id)
        result = dict(action.result or {})
        if action.status != AgentActionStatus.APPLIED or result.get("undone"):
            raise UndoNotPossibleError("Only an applied AI change can be undone, once.")
        project = self._writable(action.project_id)
        record = self.session.get(ProjectFile, action.file_id) if action.file_id else None
        if record is None or record.project_id != project.id:
            raise UndoNotPossibleError(f"{action.file_path} no longer exists.")
        current = self.session.scalar(
            select(func.max(FileVersion.version)).where(FileVersion.file_id == record.id)
        )
        if current is None or current != result.get("version"):
            raise UndoNotPossibleError(
                f"{record.path} changed after this AI change; restore an earlier version from the "
                "file's history instead."
            )
        file: AppliedFile | None = None
        deleted = False
        if result.get("created"):
            self.files.delete(project.id, record.id)  # the action itself stays in the history
            action.file_id = None
            deleted = True
        else:
            saved, _ = self.files.restore_version(project.id, record.id, current - 1)
            file = AppliedFile(
                file_id=saved.id,
                path=saved.path,
                content=saved.content or "",
                content_hash=saved.content_hash or "",
                version=self.session.scalar(
                    select(func.max(FileVersion.version)).where(FileVersion.file_id == saved.id)
                ),
            )
        action.result = {**result, "undone": True, "undone_at": datetime.now(UTC).isoformat()}
        self.session.commit()
        audit("agent_action_undone", user=self.owner.id, action=action.id, deleted=deleted)
        return UndoResponse(action=action_out(action, self._group_size(action)), file=file, deleted=deleted)

    def reject(self, action_id: uuid.UUID) -> ActionDecisionResponse:
        action = self._owned(action_id)
        self._pending([action])
        size = self._group_size(action)
        if size > 1:
            raise GroupDecisionRequiredError(size)
        self._reject_all([action])
        return ActionDecisionResponse(action=action_out(action))

    def approve_group(self, group_id: uuid.UUID) -> GroupDecisionResponse:
        actions = self._owned_group(group_id)
        applied = self._approve_all(actions)
        return GroupDecisionResponse(
            group_id=group_id, actions=[action_out(a, len(actions)) for a in actions], files=applied
        )

    def reject_group(self, group_id: uuid.UUID) -> GroupDecisionResponse:
        actions = self._owned_group(group_id)
        self._pending(actions)
        self._reject_all(actions)
        return GroupDecisionResponse(
            group_id=group_id, actions=[action_out(a, len(actions)) for a in actions]
        )

    def _reject_all(self, actions: list[AgentAction]) -> None:
        project = self.projects.get(actions[0].project_id)
        now = datetime.now(UTC)
        for action in actions:
            action.status = AgentActionStatus.REJECTED
            action.decided_at = now
            action.result = {}
            ActivityRecorder(self.session, self.owner).record(
                ActivityType.AGENT_ACTION_REJECTED,
                project,
                file_path=action.file_path,
                details={"action_id": str(action.id), "run_id": str(action.run_id)},
            )
        self.session.commit()
        for action in actions:
            audit("agent_action_rejected", user=self.owner.id, project=project.id, action=action.id)
