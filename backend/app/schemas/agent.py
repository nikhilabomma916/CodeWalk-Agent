"""Agent (Module 11): requests, runs, progress events, tool-call records, and proposed changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.ai import DiagnosticInput
from app.schemas.common import ProjectFilePath

MAX_MESSAGE_CHARS = 4000
MAX_SELECTION_CHARS = 20_000
MAX_DIAGNOSTICS = 50


class SelectionRange(BaseModel):
    """1-based, inclusive start; end is exclusive of nothing (Monaco-style positions)."""

    model_config = ConfigDict(extra="forbid")

    start_line: int = Field(ge=1, le=1_000_000)
    start_column: int = Field(ge=1, le=100_000)
    end_line: int = Field(ge=1, le=1_000_000)
    end_column: int = Field(ge=1, le=100_000)

    @model_validator(mode="after")
    def _ordered(self) -> SelectionRange:
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise ValueError("The selection ends before it starts.")
        return self


class AgentRunRequest(BaseModel):
    """What the developer asked, and where they are. Only ids and the open file travel here; everything
    else is retrieved server-side from the developer's own project."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    file_path: ProjectFilePath | None = Field(default=None, description="The file open in the editor.")
    code: str | None = Field(
        default=None, description="The open file's editor content (may be unsaved). Requires file_path."
    )
    selection: SelectionRange | None = Field(default=None, description="Selected range in the open file.")
    diagnostics: list[DiagnosticInput] = Field(
        default_factory=list, max_length=MAX_DIAGNOSTICS, description="Problems currently shown for the file."
    )

    @model_validator(mode="after")
    def _file_context(self) -> AgentRunRequest:
        if self.message.strip() == "":
            raise ValueError("The message is empty.")
        if (self.code is not None or self.selection is not None) and self.file_path is None:
            raise ValueError("code and selection need file_path.")
        return self


class ToolPermission(StrEnum):
    READ_ONLY = "read_only"
    PROPOSED_CHANGE = "proposed_change"
    WRITE = "write"  # never callable by the model; only an approval endpoint writes


class AgentEventType(StrEnum):
    STARTED = "started"
    PLANNING = "planning"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    TOOL_DENIED = "tool_denied"
    ACTION_PROPOSED = "action_proposed"
    RESPONSE = "response"
    LIMIT_REACHED = "limit_reached"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentEvent(BaseModel):
    """A user-facing progress update. Never contains model reasoning, only what is being done."""

    type: AgentEventType
    message: str
    at: datetime
    tool: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    index: int
    tool: str
    permission: ToolPermission | None
    arguments: dict[str, Any] = Field(description="Validated arguments (bounded; no file contents).")
    status: str = Field(description="ok | error | denied")
    summary: str
    duration_ms: int
    error_code: str | None = None


class ProposedChange(BaseModel):
    """One exact replacement in the file the action targets (1-based positions)."""

    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    original_text: str
    replacement_text: str


class AgentActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    kind: str = "code_change"
    status: str
    file_path: str
    summary: str
    explanation: str
    changes: list[ProposedChange]
    diff: str
    base_content_hash: str
    validation: str = Field(
        default="valid", description="Ranges were checked against the file and the change is bounded."
    )
    created_at: datetime
    decided_at: datetime | None
    result: dict[str, Any]


class AgentRunError(BaseModel):
    code: str
    message: str


class AgentRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str = Field(description="completed | limit_reached | failed")
    message: str
    file_path: str | None
    answer: str | None
    provider: str | None
    model: str | None
    error: AgentRunError | None
    events: list[AgentEvent]
    tool_calls: list[ToolCallRecord]
    actions: list[AgentActionOut]
    warnings: list[str]
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None


class AgentToolInfo(BaseModel):
    name: str
    description: str
    permission: ToolPermission


class AgentStatusResponse(BaseModel):
    available: bool
    detail: str | None
    tools: list[AgentToolInfo]
    max_steps: int
    max_actions: int


class AppliedFile(BaseModel):
    file_id: uuid.UUID
    path: str
    content: str
    content_hash: str
    version: int | None


class ActionDecisionResponse(BaseModel):
    action: AgentActionOut
    file: AppliedFile | None = Field(default=None, description="The saved file, after an approval.")
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=list, description="Deterministic analysis of the saved file, after an approval."
    )
