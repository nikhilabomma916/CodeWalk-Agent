"""In-memory search index of one project, built from Module 5 project intelligence.

The index holds the stored files' lines, symbols, imports, and import
relationships. It is cached per project and reused while the project's files
are unchanged: the cache key is the set of (path, content hash) pairs, which is
read with one metadata query. Nothing is read from the filesystem.

When files change, the next index is assembled from the previous one: only files whose content
hash changed (or that are new) are loaded and parsed again; every other file's lines and symbols
are reused. Imports are then resolved again for all files, because an added, removed, or renamed
file can change where another file's import points. The result equals a full rebuild.
"""

from __future__ import annotations

import posixpath
import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.services.languages import Language, detect_language
from app.services.project_intelligence.models import CodeSymbol, FileStructure, ImportRecord
from app.services.project_intelligence.relationships import ImportResolution
from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES, is_secret_path

Fingerprint = tuple[tuple[str, str | None], ...]
# Import resolution reads these files' contents (path aliases, baseUrl).
CONFIG_FILE_NAMES = frozenset({"tsconfig.json", "jsconfig.json"})


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


@dataclass(frozen=True)
class LoadedFile:
    """One stored file read for (re)indexing: its content and its structure (empty when the language
    has no structure support, the content is not stored, or extraction failed)."""

    path: str
    content_hash: str | None
    content: str | None
    structure: FileStructure


@dataclass
class ProjectIndex:
    files: dict[str, IndexedFile]
    # file -> project files it imports / project files importing it
    imports_of: dict[str, set[str]]
    imported_by: dict[str, set[str]]
    # Every stored path (searchable or not) with its content hash, and the contents of import
    # configuration files: what the next incremental assembly starts from.
    hashes: dict[str, str | None] = field(default_factory=dict)
    configs: dict[str, str | None] = field(default_factory=dict)

    @property
    def fingerprint(self) -> Fingerprint:
        return fingerprint_of(list(self.hashes.items()))

    def related_to(self, path: str) -> set[str]:
        return self.imports_of.get(path, set()) | self.imported_by.get(path, set())

    def stale_paths(self, hashes: Mapping[str, str | None]) -> list[str]:
        """Paths in ``hashes`` that this index does not hold with the same content hash."""
        return [
            path for path, digest in hashes.items() if path not in self.hashes or self.hashes[path] != digest
        ]

    @classmethod
    def assemble(
        cls,
        hashes: Mapping[str, str | None],
        loaded: Mapping[str, LoadedFile],
        previous: ProjectIndex | None = None,
    ) -> ProjectIndex:
        """The index of a project whose stored files are ``hashes`` (path -> content hash, in path order).

        ``loaded`` holds every file that ``previous`` does not have with the same hash (every file when
        there is no previous index); all other files are taken from ``previous`` unchanged.
        """
        files: dict[str, IndexedFile] = {}
        configs: dict[str, str | None] = {}
        for path in hashes:
            fresh = loaded.get(path)
            if posixpath.basename(path) in CONFIG_FILE_NAMES:
                if fresh is not None:
                    configs[path] = fresh.content
                elif previous is not None:
                    configs[path] = previous.configs.get(path)
            if not is_searchable(path):
                continue
            if fresh is not None:
                files[path] = IndexedFile(
                    path=path,
                    name=posixpath.basename(path),
                    language=detect_language(path),
                    lines=fresh.content.splitlines() if fresh.content is not None else None,
                    symbols=list(fresh.structure.symbols),
                    imports=list(fresh.structure.imports),
                )
            elif previous is not None and path in previous.files:
                files[path] = previous.files[path]

        # Imports are resolved against every stored path, as project intelligence does; only edges
        # between searchable files are kept. Records are copied, never changed in place: an older
        # index may still be in use by another request.
        resolution = ImportResolution({path: detect_language(path) for path in hashes}, configs)
        imports_of: dict[str, set[str]] = {}
        imported_by: dict[str, set[str]] = {}
        for path, file in list(files.items()):
            if not file.imports:
                continue
            records: list[ImportRecord] = []
            for record in file.imports:
                resolved, targets = resolution.resolve(path, record)
                if record.resolved_path != resolved:
                    record = record.model_copy(update={"resolved_path": resolved})
                records.append(record)
                for target in targets:
                    if target != path and target in files:
                        imports_of.setdefault(path, set()).add(target)
                        imported_by.setdefault(target, set()).add(path)
            if any(new is not old for new, old in zip(records, file.imports, strict=True)):
                files[path] = replace(file, imports=records)
        return cls(
            files=files,
            imports_of=imports_of,
            imported_by=imported_by,
            hashes=dict(hashes),
            configs=configs,
        )


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

    def latest(self, project_id: uuid.UUID) -> ProjectIndex | None:
        """The cached index of a project whatever its fingerprint (the base for an incremental update)."""
        with self._lock:
            entry = self._entries.get(project_id)
            return entry[1] if entry is not None else None

    def put(self, project_id: uuid.UUID, fingerprint: Fingerprint, index: ProjectIndex) -> None:
        with self._lock:
            self._entries[project_id] = (fingerprint, index)
            self._entries.move_to_end(project_id)
            while len(self._entries) > self.max_projects:
                self._entries.popitem(last=False)


def fingerprint_of(pairs: Sequence[tuple[str, str | None]]) -> Fingerprint:
    return tuple(sorted(pairs))
