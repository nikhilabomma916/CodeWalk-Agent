"""In-memory search index of one project, built from Module 5 project intelligence.

The index holds the stored files' lines, symbols, imports, and import
relationships. It is cached per project and reused while the project's files
are unchanged: the cache key is the set of (path, content hash) pairs, which is
read with one metadata query. Nothing is read from the filesystem.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.languages import Language
from app.services.project_intelligence.models import (
    CodeSymbol,
    ImportRecord,
    ProjectAnalysisResult,
    RelationshipKind,
    TargetKind,
)
from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES, is_secret_path

Fingerprint = tuple[tuple[str, str | None], ...]


def is_searchable(path: str) -> bool:
    """Ignored folders and secret files are never searched, even if a record exists."""
    *folders, _ = path.split("/")
    return not any(folder in DEFAULT_IGNORED_DIRECTORIES for folder in folders) and not is_secret_path(path)


@dataclass
class IndexedFile:
    path: str
    name: str
    language: Language
    lines: list[str] | None  # None for binary/oversized files (no stored content)
    symbols: list[CodeSymbol] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)


@dataclass
class ProjectIndex:
    files: dict[str, IndexedFile]
    # file -> project files it imports / project files importing it
    imports_of: dict[str, set[str]]
    imported_by: dict[str, set[str]]

    @classmethod
    def build(cls, structure: ProjectAnalysisResult, contents: dict[str, str | None]) -> ProjectIndex:
        files: dict[str, IndexedFile] = {}
        for info in structure.files:
            if not is_searchable(info.path):
                continue
            content = contents.get(info.path)
            files[info.path] = IndexedFile(
                path=info.path,
                name=info.name,
                language=info.language,
                lines=content.splitlines() if content is not None else None,
                symbols=list(info.symbols),
                imports=list(info.imports),
            )
        imports_of: dict[str, set[str]] = {}
        imported_by: dict[str, set[str]] = {}
        for rel in structure.relationships:
            internal = rel.kind is RelationshipKind.IMPORTS and rel.target_kind is TargetKind.FILE
            if internal and rel.source in files and rel.target in files:
                imports_of.setdefault(rel.source, set()).add(rel.target)
                imported_by.setdefault(rel.target, set()).add(rel.source)
        return cls(files=files, imports_of=imports_of, imported_by=imported_by)

    def related_to(self, path: str) -> set[str]:
        return self.imports_of.get(path, set()) | self.imported_by.get(path, set())


class IndexCache:
    """Process-local LRU of project indexes (thread-safe). Each worker keeps its own."""

    def __init__(self, max_projects: int = 32) -> None:
        self.max_projects = max_projects
        self._entries: OrderedDict[uuid.UUID, tuple[Fingerprint, ProjectIndex]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, project_id: uuid.UUID, fingerprint: Fingerprint) -> ProjectIndex | None:
        with self._lock:
            entry = self._entries.get(project_id)
            if entry is None or entry[0] != fingerprint:
                return None
            self._entries.move_to_end(project_id)
            return entry[1]

    def put(self, project_id: uuid.UUID, fingerprint: Fingerprint, index: ProjectIndex) -> None:
        with self._lock:
            self._entries[project_id] = (fingerprint, index)
            self._entries.move_to_end(project_id)
            while len(self._entries) > self.max_projects:
                self._entries.popitem(last=False)


def fingerprint_of(pairs: Sequence[tuple[str, str | None]]) -> Fingerprint:
    return tuple(sorted(pairs))
