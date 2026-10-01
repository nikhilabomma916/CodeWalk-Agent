"""Persistence model: projects, files, analyses, diagnostics."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.services.analysis.models import DiagnosticCategory, Severity

MAX_PATH_LENGTH = 1024


class AnalysisType(StrEnum):
    CODE = "code"
    PROJECT_INTELLIGENCE = "project_intelligence"


class AnalysisStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    # VARCHAR + CHECK constraint (not a native PG enum): adding values later is a simple migration.
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Folder relative to CODEWALK_WORKSPACE_ROOT when the project is linked to a
    # server directory; None for projects whose files live only in the database.
    root_path: Mapped[str | None] = mapped_column(String(MAX_PATH_LENGTH))

    files: Mapped[list[ProjectFile]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # Project names are unique regardless of letter case.
        Index("uq_projects_lower_name", func.lower(name), unique=True),
    )


class ProjectFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "files"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(MAX_PATH_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    # None when the file is not stored (binary or over the size limit).
    content: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    # Deterministic structure (symbols, imports) from project intelligence, cached per content hash.
    structure: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    project: Mapped[Project] = relationship(back_populates="files")

    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_files_project_id_path"),)


class Analysis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "analyses"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    analysis_type: Mapped[AnalysisType] = mapped_column(_enum(AnalysisType, "analysis_type"), nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(_enum(AnalysisStatus, "analysis_status"), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostic_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Capabilities, analyzer versions, statistics, errors. Structured for later AI modules.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    diagnostics: Mapped[list[DiagnosticRecord]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_analyses_project_id_created_at", "project_id", "created_at"),
        Index("ix_analyses_file_id_created_at", "file_id", "created_at"),
    )


class DiagnosticRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "diagnostics"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "diagnostic_severity"), nullable=False)
    category: Mapped[DiagnosticCategory] = mapped_column(
        _enum(DiagnosticCategory, "diagnostic_category"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_code: Mapped[str | None] = mapped_column(String(64))
    file_path: Mapped[str | None] = mapped_column(String(MAX_PATH_LENGTH))
    line: Mapped[int] = mapped_column(Integer, nullable=False)
    column: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_column: Mapped[int] = mapped_column(Integer, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text)
    documentation_url: Mapped[str | None] = mapped_column(String(512))
    fixable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    analysis: Mapped[Analysis] = relationship(back_populates="diagnostics")
