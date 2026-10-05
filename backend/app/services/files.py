"""File business rules. File content is user data: stored and analyzed, never executed.

Every content change (create, edit, restore) is recorded as a new file version;
only the newest ``file_version_history_limit`` versions are kept per file.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableSequence, Sequence
from pathlib import PurePosixPath

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError, UnsafePathError
from app.db.models import (
    ActivityType,
    Analysis,
    FileVersion,
    FileVersionSource,
    Project,
    ProjectFile,
    ProjectOrigin,
    User,
)
from app.repositories.file_versions import FileVersionRepository
from app.repositories.files import FileRepository
from app.repositories.projects import ProjectRepository
from app.schemas.common import RelativePath
from app.schemas.projects import FileCreate, FileImportItem, FileImportSkipped, FileUpdate
from app.services.activity import ActivityRecorder
from app.services.analysis.service import AnalysisService
from app.services.file_content import file_values
from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES, is_secret_path
from app.services.projects import ProjectService
from app.utils.paths import normalize_relative_path

_RELATIVE_PATH: TypeAdapter[str] = TypeAdapter(RelativePath)

# Files a developer can create directly in Coding (programming and development files only).
CODE_FILE_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".html",
        ".css",
        ".scss",
        ".sql",
        ".json",
        ".yaml",
        ".yml",
        ".md",
    }
)
MAX_CODE_FILE_NAME_LENGTH = 255
_FORBIDDEN_NAME_CHARACTERS = frozenset('<>:"|?*')


class InvalidFileNameError(AppError):
    status_code = 422
    code = "invalid_file_name"


class UnsupportedFileTypeError(AppError):
    status_code = 422
    code = "unsupported_file_type"


class InvalidMoveError(AppError):
    status_code = 422
    code = "invalid_move"


class ContentTooLargeError(AppError):
    status_code = 413
    code = "content_too_large"


class ProjectReadOnlyError(ConflictError):
    code = "project_read_only"

    def __init__(self) -> None:
        super().__init__("This project is linked to a server folder; its files are updated by rescanning.")


class FileService:
    def __init__(self, session: Session, settings: Settings, analysis: AnalysisService, owner: User) -> None:
        self.session = session
        self.settings = settings
        self.analysis = analysis
        self.owner = owner
        self.projects = ProjectService(session, settings, owner)
        self.project_repository = ProjectRepository(session)
        self.files = FileRepository(session)
        self.versions = FileVersionRepository(session)
        self.activity = ActivityRecorder(session, owner)

    def _writable_project(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(project_id)
        if project.root_path is not None:
            raise ProjectReadOnlyError()
        return project

    def _check_size(self, content: str) -> None:
        size = len(content.encode("utf-8"))
        if size > self.settings.max_source_bytes:
            raise ContentTooLargeError(
                f"File content is {size} bytes; the limit is {self.settings.max_source_bytes}."
            )

    def _record_version(self, record: ProjectFile, source: FileVersionSource) -> int | None:
        """Snapshot the content as a new version; returns its number (None without content)."""
        version = self.versions.add(record, source=source, author_id=self.owner.id)
        if version is None:
            return None
        self.versions.prune(record.id, keep=self.settings.file_version_history_limit)
        return version.version

    def get(self, project_id: uuid.UUID, file_id: uuid.UUID) -> ProjectFile:
        self.projects.get(project_id)
        record = self.files.get(project_id, file_id)
        if record is None:
            raise NotFoundError("File not found.", code="file_not_found")
        return record

    def list(self, project_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[ProjectFile], int]:
        self.projects.get(project_id)
        return self.files.list_metadata(project_id, limit=limit, offset=offset)

    def create(
        self, project_id: uuid.UUID, data: FileCreate, *, commit: bool = True
    ) -> tuple[ProjectFile, Analysis | None]:
        """``commit=False`` leaves the transaction open, so several saves can be committed together."""
        project = self._writable_project(project_id)
        self._check_size(data.content)
        if self.files.get_by_path(project_id, data.path) is not None:
            raise ConflictError(f"{data.path} already exists.", code="file_exists")
        try:
            record = self.files.create(project_id=project_id, **file_values(data.path, data.content))
            version = self._record_version(record, FileVersionSource.CREATE)
            analysis = self.analysis.record_file_analysis(record)[0] if data.content else None
            self.activity.record(
                ActivityType.FILE_CREATED,
                project,
                file=record,
                analysis=analysis,
                details={"version": version},
            )
            self.project_repository.touch(project)
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{data.path} already exists.", code="file_exists") from None
        return record, analysis

    def create_code_file(self, project_id: uuid.UUID, name: str) -> tuple[ProjectFile, Analysis | None]:
        """Creates an empty code file at the project root from a file name only (Coding: "+ New File").

        Stricter than the general file API: no folders, a programming/development extension, and
        never an existing file (409). Uploaded projects are analysis copies and are not edited here.
        """
        if self.projects.get(project_id).origin is ProjectOrigin.UPLOAD:
            raise ConflictError("Uploaded projects are read-only analysis copies.", code="project_read_only")
        name = name.strip()
        if not name:
            raise InvalidFileNameError("Enter a file name, for example main.py.")
        if len(name) > MAX_CODE_FILE_NAME_LENGTH:
            raise InvalidFileNameError(f"File names can have at most {MAX_CODE_FILE_NAME_LENGTH} characters.")
        if "/" in name or "\\" in name:
            raise InvalidFileNameError("Enter a file name only, without folders.")
        if name in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise InvalidFileNameError("The file name contains characters that are not allowed.")
        if any(c in _FORBIDDEN_NAME_CHARACTERS for c in name):
            raise InvalidFileNameError('File names cannot contain < > : " | ? *.')
        try:
            normalize_relative_path(name)  # the shared path rules (absolute paths, drives, ..)
        except UnsafePathError as exc:
            raise InvalidFileNameError(exc.message) from None
        if is_secret_path(name):
            raise InvalidFileNameError("Credentials files such as .env are not created in Coding.")
        if PurePosixPath(name).suffix.lower() not in CODE_FILE_EXTENSIONS:
            raise UnsupportedFileTypeError(
                "Unsupported file type. CodeWalk Coding supports programming and development files."
            )
        return self.create(project_id, FileCreate(path=name, content=""))

    def _under(self, project_id: uuid.UUID, path: str) -> Sequence[ProjectFile]:
        """The file at ``path``, or every file in the folder ``path``; 404 when there is neither."""
        record = self.files.get_by_path(project_id, path)
        if record is not None:
            return [record]
        prefix = path.rstrip("/") + "/"
        records = list(self.files.list_with_prefix(project_id, prefix))
        if not records:
            raise NotFoundError(f"{path} does not exist.", code="path_not_found")
        return records

    def rename_path(self, project_id: uuid.UUID, from_path: str, to_path: str) -> Sequence[str]:
        """Renames/moves a file, or a folder with all its files, atomically. Returns the new paths."""
        self._writable_project(project_id)
        if from_path == to_path:
            return []
        records = self._under(project_id, from_path)
        single = len(records) == 1 and records[0].path == from_path
        if not single and (to_path + "/").startswith(from_path.rstrip("/") + "/"):
            raise InvalidMoveError("A folder cannot be moved into itself.")
        moving = {r.path for r in records}
        moves: MutableSequence[tuple[ProjectFile, str]] = []
        for record in records:
            wanted = to_path if single else to_path + record.path[len(from_path.rstrip("/")) :]
            try:
                new_path = _RELATIVE_PATH.validate_python(wanted)
            except ValidationError:
                raise InvalidMoveError(f"{wanted} is not a valid project path.") from None
            if new_path not in moving and self.files.get_by_path(project_id, new_path) is not None:
                raise ConflictError(f"{new_path} already exists.", code="file_exists")
            moves.append((record, new_path))
        # Shortest old paths first: when a folder moves up into an ancestor, a file's new path can
        # only equal a shorter old path, which has already been moved by then (into-itself is refused).
        for record, new_path in sorted(moves, key=lambda move: len(move[0].path)):
            self._update(
                project_id, record.id, FileUpdate(path=new_path), FileVersionSource.EDIT, commit=False
            )
            self.session.flush()
        self.session.commit()
        return [new_path for _, new_path in moves]

    def delete_path(self, project_id: uuid.UUID, path: str) -> Sequence[str]:
        """Deletes a file, or a folder with all its files, in one transaction. Returns the paths."""
        project = self._writable_project(project_id)
        records = self._under(project_id, path)
        deleted = [r.path for r in records]
        for record in records:
            self.activity.record(ActivityType.FILE_DELETED, project, file_path=record.path)
            self.files.delete(record)
        self.project_repository.touch(project)
        self.session.commit()
        return deleted

    def copy_files(self, source_id: uuid.UUID, target_id: uuid.UUID) -> int:
        """Copies every stored file of the developer's project ``source_id`` into ``target_id`` (one
        transaction; each file is created like a normal save: version 1, analysis, activity)."""
        self.projects.get(source_id)  # ownership: 404 for another user's project
        copied = 0
        for record in self.files.list_all(source_id):
            if record.content is None:  # listed but not stored (binary or too large when scanned)
                continue
            self.create(target_id, FileCreate(path=record.path, content=record.content), commit=False)
            copied += 1
        self.session.commit()
        return copied

    def import_files(
        self, project_id: uuid.UUID, items: Sequence[FileImportItem]
    ) -> tuple[Sequence[ProjectFile], Sequence[FileImportSkipped]]:
        """Stores one batch of files uploaded from a local folder (all or nothing for the batch).

        Each file is checked on its own: an unsafe path, a credentials file, a dependency/build
        folder, oversized content, an existing path, or the project file limit skips that file with
        a reason instead of failing the batch. Existing files are never overwritten.
        """
        self._writable_project(project_id)
        existing = self.files.list_metadata(project_id, limit=1, offset=0)[1]
        created: list[ProjectFile] = []
        skipped: list[FileImportSkipped] = []
        seen: set[str] = set()

        def skip(path: str, reason: str, message: str) -> None:
            skipped.append(FileImportSkipped(path=path, reason=reason, message=message))

        for item in items:
            try:
                path = _RELATIVE_PATH.validate_python(item.path)
            except ValidationError:
                skip(item.path, "invalid_path", "The path is not a safe project-relative path.")
                continue
            folders = path.split("/")[:-1]
            if is_secret_path(path):
                skip(path, "secret", "Credentials files such as .env are never stored.")
            elif any(folder in DEFAULT_IGNORED_DIRECTORIES for folder in folders):
                skip(path, "ignored", "Dependency and build folders are not stored.")
            elif len(item.content.encode("utf-8")) > self.settings.max_source_bytes:
                skip(path, "too_large", f"Files over {self.settings.max_source_bytes} bytes are not stored.")
            elif path in seen:
                skip(path, "duplicate", "The same path appears twice in this upload.")
            elif self.files.get_by_path(project_id, path) is not None:
                skip(path, "exists", "A file with this path already exists; it was not overwritten.")
            elif existing + len(created) >= self.settings.scan_max_files:
                skip(path, "limit", f"The project already has {self.settings.scan_max_files} files.")
            else:
                seen.add(path)
                record, _ = self.create(project_id, FileCreate(path=path, content=item.content), commit=False)
                created.append(record)
                continue
            seen.add(path)
        self.session.commit()
        return created, skipped

    def update(
        self, project_id: uuid.UUID, file_id: uuid.UUID, data: FileUpdate, *, commit: bool = True
    ) -> tuple[ProjectFile, Analysis | None]:
        """``commit=False`` leaves the transaction open, so several saves can be committed together."""
        return self._update(project_id, file_id, data, FileVersionSource.EDIT, commit=commit)

    def _update(
        self,
        project_id: uuid.UUID,
        file_id: uuid.UUID,
        data: FileUpdate,
        source: FileVersionSource,
        *,
        restored_from: int | None = None,
        commit: bool = True,
    ) -> tuple[ProjectFile, Analysis | None]:
        project = self._writable_project(project_id)
        record = self.get(project_id, file_id)
        new_path = data.path if data.path is not None and data.path != record.path else None
        if new_path is not None and self.files.get_by_path(project_id, new_path) is not None:
            raise ConflictError(f"{new_path} already exists.", code="file_exists")
        content_changed = data.content is not None and data.content != record.content
        if data.content is not None:
            self._check_size(data.content)
        if new_path is None and not content_changed:
            return record, None

        content = data.content if content_changed else record.content
        values = file_values(new_path or record.path, content, record.size)
        if not content_changed:  # rename only: keep the cached structure
            values.pop("structure")
        analysis: Analysis | None = None
        previous_path = record.path
        details: dict[str, object] = {}
        try:
            self.files.update(record, **values)
            if content_changed:
                details["version"] = self._record_version(record, source)
                analysis = self.analysis.record_file_analysis(record)[0]
            if new_path is not None:
                details["renamed_from"] = previous_path
            if restored_from is not None:
                details["restored_from"] = restored_from
            self.activity.record(
                ActivityType.FILE_RESTORED if restored_from is not None else ActivityType.FILE_UPDATED,
                project,
                file=record,
                analysis=analysis,
                details=details,
            )
            self.project_repository.touch(project)
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(f"{new_path} already exists.", code="file_exists") from None
        if commit:
            self.session.refresh(record)
        return record, analysis

    def delete(self, project_id: uuid.UUID, file_id: uuid.UUID) -> None:
        project = self._writable_project(project_id)
        record = self.get(project_id, file_id)
        self.activity.record(ActivityType.FILE_DELETED, project, file_path=record.path)
        self.files.delete(record)
        self.project_repository.touch(project)
        self.session.commit()

    def list_versions(
        self, project_id: uuid.UUID, file_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[FileVersion], int]:
        return self.versions.list(self.get(project_id, file_id).id, limit=limit, offset=offset)

    def get_version(self, project_id: uuid.UUID, file_id: uuid.UUID, version: int) -> FileVersion:
        record = self.versions.get(self.get(project_id, file_id).id, version)
        if record is None:
            raise NotFoundError(
                "That version does not exist (it may have been pruned).", code="version_not_found"
            )
        return record

    def restore_version(
        self, project_id: uuid.UUID, file_id: uuid.UUID, version: int
    ) -> tuple[ProjectFile, Analysis | None]:
        """Make an earlier version the current content. Recorded as a new version, so it can be undone."""
        content = self.get_version(project_id, file_id, version).content
        return self._update(
            project_id, file_id, FileUpdate(content=content), FileVersionSource.RESTORE, restored_from=version
        )
