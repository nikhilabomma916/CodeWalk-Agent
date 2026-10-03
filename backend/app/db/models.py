"""Persistence model: users and login sessions, projects, files and their versions,
analyses, diagnostics, the per-user activity history, and embedded code chunks."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.vector import Vector
from app.services.analysis.models import DiagnosticCategory, Severity
from app.services.retrieval.base import EMBEDDING_DIMENSIONS

MAX_PATH_LENGTH = 1024


class AnalysisType(StrEnum):
    CODE = "code"
    PROJECT_INTELLIGENCE = "project_intelligence"
    # AI results (advisory). Details hold provider, model, and the validated answer, not the code.
    AI_REVIEW = "ai_review"
    AI_EXPLANATION = "ai_explanation"
    AI_FIX_SUGGESTION = "ai_fix_suggestion"


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


class FileVersionSource(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    RESTORE = "restore"
    SCAN = "scan"


class ActivityType(StrEnum):
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    PROJECT_ANALYZED = "project.analyzed"
    FILE_CREATED = "file.created"
    FILE_UPDATED = "file.updated"
    FILE_RESTORED = "file.restored"
    FILE_DELETED = "file.deleted"
    FILE_ANALYZED = "file.analyzed"
    AI_ANALYZED = "ai.analyzed"
    AI_EXPLAINED = "ai.explained"
    AI_FIX_SUGGESTED = "ai.fix_suggested"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Stored lower-cased; unique.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Argon2id hash (includes its own salt and parameters).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Inactive accounts cannot sign in and their existing sessions stop working.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the cookie token: a database leak does not reveal usable tokens.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    user: Mapped[User] = relationship()


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Folder relative to CODEWALK_WORKSPACE_ROOT when the project is linked to a
    # server directory; None for projects whose files live only in the database.
    root_path: Mapped[str | None] = mapped_column(String(MAX_PATH_LENGTH))

    files: Mapped[list[ProjectFile]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # Each user's project names are unique regardless of letter case.
        Index("uq_projects_owner_id_lower_name", owner_id, func.lower(name), unique=True),
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
    versions: Mapped[list[FileVersion]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_files_project_id_path"),)


class FileVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A saved state of a file's content. Version numbers start at 1 per file."""

    __tablename__ = "file_versions"

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[FileVersionSource] = mapped_column(
        _enum(FileVersionSource, "file_version_source"), nullable=False
    )
    # Who saved it; None for folder rescans or when the user was deleted.
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    file: Mapped[ProjectFile] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("file_id", "version", name="uq_file_versions_file_id_version"),)


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


class ActivityEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Something a user did, recorded in the same transaction as the action itself.

    Project name and file path are copied at the time of the event, so entries stay
    readable after a rename or delete; the foreign keys become NULL when the target
    is deleted (or, for analyses, pruned).
    """

    __tablename__ = "activity_events"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[ActivityType] = mapped_column(_enum(ActivityType, "activity_type"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    project_name: Mapped[str] = mapped_column(String(100), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    file_path: Mapped[str | None] = mapped_column(String(MAX_PATH_LENGTH))
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    # Small structured summary (diagnostic counts, version number, changed fields, ...).
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_activity_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_activity_events_project_id_created_at", "project_id", "created_at"),
    )


class CodeChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One embedded piece of a project file (a symbol or a block of lines) for semantic retrieval.

    The source text is not copied: snippets are read from ``files.content``. A chunk is current
    while its ``content_hash`` equals the file's; edited files keep their old chunks (never
    returned) until the next indexing run replaces them. ``chunk_hash`` lets that run reuse the
    vectors of unchanged chunks instead of embedding them again.
    """

    __tablename__ = "code_chunks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    # The file's content hash when the chunk was embedded.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Hash of the exact text sent to the embedding provider (including its path/symbol header).
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(255))
    symbol_kind: Mapped[str | None] = mapped_column(String(32))
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)

    __table_args__ = (
        UniqueConstraint("file_id", "embedding_model", "chunk_index", name="uq_code_chunks_file_model_index"),
        Index("ix_code_chunks_project_id_embedding_model", "project_id", "embedding_model"),
        Index("ix_code_chunks_file_id_chunk_hash", "file_id", "chunk_hash"),
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
