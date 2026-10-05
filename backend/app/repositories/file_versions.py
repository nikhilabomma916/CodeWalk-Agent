"""Data access for file version history."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, defer

from app.db.models import FileVersion, FileVersionSource, ProjectFile


class FileVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self, file: ProjectFile, *, source: FileVersionSource, author_id: uuid.UUID | None
    ) -> FileVersion | None:
        """Snapshot the file's current content as its next version (None for files without content)."""
        if file.content is None or file.content_hash is None:
            return None
        latest = self.session.scalar(
            select(func.max(FileVersion.version)).where(FileVersion.file_id == file.id)
        )
        version = FileVersion(
            file_id=file.id,
            version=(latest or 0) + 1,
            content=file.content,
            content_hash=file.content_hash,
            size=file.size,
            line_count=file.line_count,
            source=source,
            author_id=author_id,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def add_initial(
        self, files: Sequence[ProjectFile], *, source: FileVersionSource, author_id: uuid.UUID | None
    ) -> None:
        """Version 1 of files that were just added (not flushed yet): one flush for all of them.
        New files have no earlier versions, so there is nothing to number after or to prune."""
        for file in files:
            if file.content is None or file.content_hash is None:
                continue
            self.session.add(
                FileVersion(
                    file=file,
                    version=1,
                    content=file.content,
                    content_hash=file.content_hash,
                    size=file.size,
                    line_count=file.line_count,
                    source=source,
                    author_id=author_id,
                )
            )
        self.session.flush()

    def list(self, file_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[FileVersion], int]:
        """Newest first, without content."""
        total = (
            self.session.scalar(
                select(func.count()).select_from(FileVersion).where(FileVersion.file_id == file_id)
            )
            or 0
        )
        items = self.session.scalars(
            select(FileVersion)
            .options(defer(FileVersion.content))
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return items, total

    def get(self, file_id: uuid.UUID, version: int) -> FileVersion | None:
        return self.session.scalar(
            select(FileVersion).where(FileVersion.file_id == file_id, FileVersion.version == version)
        )

    def prune(self, file_id: uuid.UUID, keep: int) -> int:
        """Delete all but the newest ``keep`` versions of a file."""
        keep_versions = (
            select(FileVersion.version)
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version.desc())
            .limit(keep)
        )
        result = self.session.execute(
            delete(FileVersion).where(
                FileVersion.file_id == file_id, FileVersion.version.not_in(keep_versions)
            )
        )
        self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0)
