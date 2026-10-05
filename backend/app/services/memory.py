"""Project-scoped AI memory (Module 17): short notes a developer saves for the AI about one project.

Rules:
- Only the developer writes memory, through the API. The model never stores anything here.
- Scoped to one user's project (ownership is checked through ``ProjectService``), deleted with it.
- Bounded: at most ``MAX_ITEMS`` items of at most 500 characters per project.
- Text that looks like a credential (keys, tokens, passwords, private keys, connection strings with
  passwords) is refused, so secrets never reach the database or a prompt.
- In prompts, memory is quoted as escaped data and cannot change CodeWalk's policy.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.models import Project, ProjectMemory, User
from app.schemas.insights import MemoryCreate
from app.services.projects import ProjectService

MAX_ITEMS = 50
MAX_PROMPT_ITEMS = 20

# Credential-shaped text. Deliberately broad: a refused note can be rephrased; a stored secret cannot be
# taken back out of every prompt it reached.
_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\b(sk|rk|pk)[-_](live|test|ant|proj)?[-_]?[A-Za-z0-9_-]{16,}"),  # provider API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"://[^\s:/@]+:[^\s@/]+@"),  # URL with an embedded password
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)"
        r"\s*[:=]\s*\S{4,}"
    ),
)


class MemoryLimitError(ConflictError):
    code = "memory_limit_reached"


class SecretInMemoryError(AppError):
    status_code = 422
    code = "memory_contains_secret"

    def __init__(self) -> None:
        super().__init__(
            "This note looks like it contains a credential (key, token, password, or private key). "
            "Project memory never stores secrets; describe the convention without the value."
        )


def looks_like_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


class MemoryService:
    def __init__(self, session: Session, settings: Settings, owner: User) -> None:
        self.session = session
        self.owner = owner
        self.projects = ProjectService(session, settings, owner)

    def items(self, project_id: uuid.UUID) -> Sequence[ProjectMemory]:
        project = self.projects.get(project_id)
        return self.session.scalars(
            select(ProjectMemory)
            .where(ProjectMemory.project_id == project.id, ProjectMemory.user_id == self.owner.id)
            .order_by(ProjectMemory.created_at, ProjectMemory.id)
            .limit(MAX_ITEMS)
        ).all()

    def for_prompt(self, project_id: uuid.UUID) -> list[ProjectMemory]:
        """The newest items to show the AI (ownership was checked by the caller's project lookup)."""
        items = self.session.scalars(
            select(ProjectMemory)
            .where(ProjectMemory.project_id == project_id, ProjectMemory.user_id == self.owner.id)
            .order_by(ProjectMemory.created_at.desc(), ProjectMemory.id)
            .limit(MAX_PROMPT_ITEMS)
        ).all()
        return list(reversed(items))

    def add(self, project_id: uuid.UUID, data: MemoryCreate) -> ProjectMemory:
        project = self.projects.get(project_id)
        text = " ".join(data.text.split())
        if looks_like_secret(text):
            audit("memory_secret_refused", level=logging.WARNING, user=self.owner.id, project=project.id)
            raise SecretInMemoryError()
        # Lock the project row so concurrent adds cannot exceed the limit.
        self.session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
        count = self.session.scalar(
            select(func.count())
            .select_from(ProjectMemory)
            .where(ProjectMemory.project_id == project.id, ProjectMemory.user_id == self.owner.id)
        )
        if (count or 0) >= MAX_ITEMS:
            raise MemoryLimitError(f"A project can hold at most {MAX_ITEMS} memory items; delete one first.")
        item = ProjectMemory(user_id=self.owner.id, project_id=project.id, kind=data.kind, text=text)
        self.session.add(item)
        self.session.commit()
        audit("memory_added", user=self.owner.id, project=project.id, memory=item.id, kind=data.kind.value)
        return item

    def delete(self, project_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        project = self.projects.get(project_id)
        item = self.session.scalar(
            select(ProjectMemory).where(
                ProjectMemory.id == memory_id,
                ProjectMemory.project_id == project.id,
                ProjectMemory.user_id == self.owner.id,
            )
        )
        if item is None:
            raise NotFoundError("Memory item not found.", code="memory_not_found")
        self.session.delete(item)
        self.session.commit()
        audit("memory_deleted", user=self.owner.id, project=project.id, memory=memory_id)
