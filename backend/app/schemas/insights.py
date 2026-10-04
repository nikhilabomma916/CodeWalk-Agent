"""Requests for project insights and project memory (Module 17)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import MemoryKind
from app.schemas.common import ProjectFilePath

SYMBOL_PATTERN = r"^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$"


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: ProjectFilePath
    symbol: str | None = Field(
        default=None, max_length=200, pattern=SYMBOL_PATTERN, description="A function, class, or method name."
    )


class ReferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, pattern=SYMBOL_PATTERN)


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    text: str = Field(min_length=3, max_length=500)


class MemoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: MemoryKind
    text: str
    created_at: datetime


class MemoryList(BaseModel):
    items: list[MemoryItem]
    limit: int = Field(description="Most items one project can hold.")
