"""Approving or rejecting an agent's proposed change: the only path from a proposal to a file write.

Approval re-checks everything at decision time, never trusting the proposal or the client:
1. the action belongs to the signed-in user and is still pending;
2. its project is the user's and is editable (not folder-linked);
3. the file still exists at the same path;
4. the file's content hash equals the hash the proposal was computed against, and every
   change's original text is still exactly at its range (otherwise: ``stale``, not applied);
5. the result is bounded (size, changed lines).
The file is then saved through ``FileService`` (new version, deterministic re-analysis,
history), and the resulting diagnostics are returned. Rejection changes no file.
"""

from __future__ import annotations

import logging
import uuid
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
    User,
)
from app.repositories.analyses import DiagnosticRepository
from app.repositories.files import FileRepository
from app.schemas.agent import ActionDecisionResponse, AppliedFile, ProposedChange
from app.schemas.ai import CodeEdit
from app.schemas.analysis import StoredDiagnostic
from app.schemas.projects import FileUpdate
from app.services.activity import ActivityRecorder
from app.services.agent.service import action_out
from app.services.ai import edits as edit_rules
from app.services.files import FileService, ProjectReadOnlyError
from app.services.projects import ProjectService

logger = logging.getLogger(__name__)


class ActionNotPendingError(ConflictError):
    code = "action_not_pending"


class StaleActionError(AppError):
    status_code = 409
    code = "stale_action"


class AgentActionService:
    def __init__(self, session: Session, owner: User, files: FileService, projects: ProjectService) -> None:
        self.session = session
        self.owner = owner
        self.files = files
        self.projects = projects

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

    def _pending(self, action: AgentAction) -> None:
        if action.status is not AgentActionStatus.PENDING:
            raise ActionNotPendingError(f"This proposed change was already {action.status.value}.")

    def _stale(self, action: AgentAction, reason: str, message: str) -> StaleActionError:
        action.status = AgentActionStatus.STALE
        action.decided_at = datetime.now(UTC)
        action.result = {"reason": reason}
        self.session.commit()
        audit(
            "agent_action_stale", level=logging.WARNING, user=self.owner.id, action=action.id, reason=reason
        )
        return StaleActionError(message)

    def approve(self, action_id: uuid.UUID) -> ActionDecisionResponse:
        action = self._owned(action_id)
        self._pending(action)
        project = self.projects.get(action.project_id)
        if project.root_path is not None:
            raise ProjectReadOnlyError()
        record = FileRepository(self.session).get(project.id, action.file_id)
        if record is None:
            raise self._stale(action, "file_missing", "The file no longer exists.")
        if record.path != action.file_path:
            raise self._stale(action, "file_moved", f"The file was renamed to {record.path}.")
        content = record.content
        if content is None or edit_rules.text_hash(content) != action.base_content_hash:
            raise self._stale(
                action,
                "content_changed",
                "The file changed after this change was proposed, so it was not applied. "
                "Ask the agent again.",
            )
        changes = [ProposedChange.model_validate(c) for c in action.changes]
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
                    raise self._stale(action, "original_mismatch", "The code to replace is no longer there.")
            updated = edit_rules.apply_edits(content, ordered)
            edit_rules.check_change_is_safe(content, updated)
        except edit_rules.InvalidEditError as exc:
            raise self._stale(
                action, "invalid", f"The proposed change can no longer be applied: {exc.message}"
            ) from None

        # Mark the decision first so it commits together with the file save below.
        action.status = AgentActionStatus.APPLIED
        action.decided_at = datetime.now(UTC)
        saved, analysis = self.files.update(project.id, record.id, FileUpdate(content=updated))
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
        }
        ActivityRecorder(self.session, self.owner).record(
            ActivityType.AGENT_ACTION_APPLIED,
            project,
            file=saved,
            analysis=analysis,
            details={"action_id": str(action.id), "run_id": str(action.run_id), "version": version},
        )
        self.session.commit()
        audit(
            "agent_action_applied", user=self.owner.id, project=project.id, action=action.id, version=version
        )
        logger.info("Agent action %s applied to %s (version %s)", action.id, saved.path, version)
        return ActionDecisionResponse(
            action=action_out(action),
            file=AppliedFile(
                file_id=saved.id,
                path=saved.path,
                content=saved.content or "",
                content_hash=saved.content_hash or "",
                version=version,
            ),
            diagnostics=diagnostics,
        )

    def reject(self, action_id: uuid.UUID) -> ActionDecisionResponse:
        action = self._owned(action_id)
        self._pending(action)
        project = self.projects.get(action.project_id)
        action.status = AgentActionStatus.REJECTED
        action.decided_at = datetime.now(UTC)
        action.result = {}
        ActivityRecorder(self.session, self.owner).record(
            ActivityType.AGENT_ACTION_REJECTED,
            project,
            file_path=action.file_path,
            details={"action_id": str(action.id), "run_id": str(action.run_id)},
        )
        self.session.commit()
        audit("agent_action_rejected", user=self.owner.id, project=project.id, action=action.id)
        return ActionDecisionResponse(action=action_out(action))
