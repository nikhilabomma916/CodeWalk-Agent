"""Backend policy for agent tool calls. The model never decides what it may do.

Before any tool runs, ``ToolPolicy.check`` verifies that the tool exists, that its
permission is one the model may use (WRITE never is: changes are applied only by an
explicit approval request), that proposal and step budgets remain, and that the same
call was not already made (repeated calls are a loop symptom). Arguments are then
validated by the tool's input model, and paths by the tool context (project files
only). Authentication and project ownership were established before the run started.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.schemas.agent import ToolPermission
from app.services.agent.tools import TOOLS, ToolSpec

MODEL_PERMISSIONS = frozenset({ToolPermission.READ_ONLY, ToolPermission.PROPOSED_CHANGE})
# Consecutive failed or denied calls before the run is stopped (the model is not making progress).
MAX_CONSECUTIVE_FAILURES = 3


class ToolDeniedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def call_key(tool: str, arguments: dict[str, Any]) -> str:
    return tool + ":" + json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class ToolPolicy:
    max_actions: int
    max_tool_calls: int = 1_000
    actions: int = 0
    calls: int = 0
    executed: set[str] = field(default_factory=set)
    consecutive_failures: int = 0

    def resolve(self, name: str | None) -> ToolSpec:
        spec = TOOLS.get(name or "")
        if spec is None:
            raise ToolDeniedError("unknown_tool", f"There is no tool named {name!r}.")
        if spec.permission not in MODEL_PERMISSIONS:
            raise ToolDeniedError("permission_denied", f"{spec.name} cannot be called by the agent.")
        return spec

    def check(self, spec: ToolSpec, arguments: dict[str, Any]) -> str:
        if self.calls >= self.max_tool_calls:
            raise ToolDeniedError(
                "tool_call_limit", f"At most {self.max_tool_calls} tool calls are allowed per request."
            )
        if spec.permission is ToolPermission.PROPOSED_CHANGE and self.actions >= self.max_actions:
            raise ToolDeniedError(
                "proposal_limit", f"At most {self.max_actions} changes can be proposed in one request."
            )
        key = call_key(spec.name, arguments)
        if key in self.executed:
            raise ToolDeniedError("repeated_call", "This exact call was already made; use its result above.")
        return key

    def succeeded(self, key: str, spec: ToolSpec) -> None:
        self.calls += 1
        self.executed.add(key)
        self.consecutive_failures = 0
        if spec.permission is ToolPermission.PROPOSED_CHANGE:
            self.actions += 1

    def failed(self, key: str | None = None) -> None:
        if key is not None:
            self.calls += 1
            self.executed.add(key)
        self.consecutive_failures += 1

    @property
    def out_of_calls(self) -> bool:
        return self.calls >= self.max_tool_calls

    @property
    def stuck(self) -> bool:
        return self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
