"""Deterministic project insights (Module 17): architecture summary, dependency impact, references,
and related tests, computed from the in-memory project index (stored files, symbols, resolved imports).

No AI is involved and nothing is executed, so these work without a provider. Relationships are labelled:

- CONFIRMED: backed by a resolved import between project files, or by a use of the name inside the
  file that defines it.
- POSSIBLE: the name appears in a file that has no import connecting it to the definition (it may
  be a different symbol with the same name, a dynamic import, or a string).

There is no call graph and no type resolution: a reference is "the identifier occurs on this line".
Every list is bounded; the report says when it was truncated.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter, deque
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.services.languages import Language
from app.services.project_intelligence.models import CodeSymbol, SymbolKind
from app.services.project_search.index import IndexedFile, ProjectIndex

MAX_ITEMS = 50
MAX_LINES_PER_FILE = 5
MAX_DEPTH = 3
MIN_POSSIBLE_NAME = 3  # shorter names match too much text to be useful evidence

CONFIRMED = "confirmed"
POSSIBLE = "possible"

_TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$)")
_CONFIG_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "requirements.txt",
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "alembic.ini",
        "dockerfile",
        ".env.example",
        "next.config.ts",
        "next.config.js",
        "next.config.mjs",
        "vite.config.ts",
        "vitest.config.mts",
        "eslint.config.mjs",
        "postcss.config.mjs",
    }
)
_CONFIG_EXTENSIONS = (".toml", ".ini", ".cfg", ".yaml", ".yml")
_DOC_EXTENSIONS = (".md", ".rst", ".txt")
_ROUTE = re.compile(
    r"@(?P<owner>[A-Za-z_][\w.]*)\.(?P<method>get|post|put|patch|delete|options|head|route|api_route)\("
    r"\s*(?P<quote>[\"'])(?P<path>[^\"']*)(?P=quote)"
)
_MODEL_MARKERS = ("__tablename__", "Mapped[", "models.Model)", "db.Model)")
_ENTRY_NAMES = frozenset({"main.py", "__main__.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.py"})


# --- models --------------------------------------------------------------------------------------


class FileRole(BaseModel):
    path: str
    role: str
    reason: str


class Component(BaseModel):
    name: str = Field(description="A top-level folder (two levels for folders such as backend/app).")
    files: int
    symbols: int
    languages: dict[str, int]
    roles: dict[str, int]


class ComponentLink(BaseModel):
    source: str
    target: str
    imports: int = Field(description="Resolved imports from files of `source` to files of `target`.")
    relationship: str = CONFIRMED


class ApiRoute(BaseModel):
    file_path: str
    line: int
    method: str
    path: str


class ArchitectureReport(BaseModel):
    files: int
    languages: dict[str, int]
    roles: dict[str, int]
    components: list[Component]
    links: list[ComponentLink]
    entry_points: list[str]
    api_routes: list[ApiRoute]
    data_models: list[str] = Field(description="Classes defined in files that declare database models.")
    tests: int
    truncated: bool
    limitations: list[str]


class Location(BaseModel):
    file_path: str
    lines: list[int] = Field(default_factory=list)
    relationship: str
    evidence: str
    role: str | None = None
    chain: list[str] = Field(default_factory=list, description="Import chain from the target, if indirect.")


class ImpactReport(BaseModel):
    file_path: str
    symbol: str | None
    definitions: list[Location]
    same_file_references: list[int]
    direct_dependents: list[Location]
    indirect_dependents: list[Location]
    possible_references: list[Location]
    dependencies: list[str] = Field(description="Project files the target file imports (confirmed).")
    external_imports: list[str]
    related_tests: list[Location]
    related_api_routes: list[ApiRoute]
    truncated: bool
    limitations: list[str]


class ReferenceReport(BaseModel):
    name: str
    definitions: list[Location]
    references: list[Location]
    truncated: bool


# --- classification ------------------------------------------------------------------------------


def classify(file: IndexedFile) -> FileRole:
    """A coarse, explainable role for a file, from its path and (for Python) a few source markers."""
    path = file.path
    name = posixpath.basename(path).lower()
    folders = path.lower().split("/")[:-1]

    def role(value: str, reason: str) -> FileRole:
        return FileRole(path=path, role=value, reason=reason)

    if _TEST_NAME.search(name) or any(f in ("tests", "test", "__tests__") for f in folders):
        return role("test", "test file name or tests folder")
    if "migrations" in folders:
        return role("migration", "inside a migrations folder")
    if (
        name in _CONFIG_NAMES
        or name.startswith(("docker-compose", ".env"))
        or name.endswith(_CONFIG_EXTENSIONS)
    ):
        return role("config", "configuration file")
    if name.endswith(_DOC_EXTENSIONS) or "docs" in folders:
        return role("docs", "documentation")
    if name.endswith((".css", ".scss", ".less")):
        return role("style", "stylesheet")
    lines = file.lines or []
    if file.language is Language.PYTHON:
        if any(_ROUTE.search(line) for line in lines):
            return role("api_route", "declares HTTP route handlers (@router.get(...) and similar)")
        if any(marker in line for line in lines for marker in _MODEL_MARKERS):
            return role("data_model", "declares database models (__tablename__ / Mapped[...])")
        if "schemas" in folders:
            return role("schema", "inside a schemas folder")
        if "services" in folders:
            return role("service", "inside a services folder")
        if "repositories" in folders:
            return role("repository", "inside a repositories folder")
    if name.endswith((".tsx", ".jsx")):
        if name in ("page.tsx", "page.jsx", "layout.tsx", "layout.jsx"):
            return role("frontend_page", "Next.js page or layout")
        return role("frontend_component", "React component file")
    if ("api" in folders or "services" in folders) and name.endswith((".ts", ".js")):
        return role("frontend_api_client", "client code under an api/services folder")
    return role("source", "other source file")


class _Roles:
    """File roles computed once per report (classification scans Python sources)."""

    def __init__(self, index: ProjectIndex) -> None:
        self.index = index
        self._roles: dict[str, FileRole] = {}

    def __call__(self, path: str) -> str:
        found = self._roles.get(path)
        if found is None:
            found = self._roles[path] = classify(self.index.files[path])
        return found.role


def _component(path: str) -> str:
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    # Two levels for the usual monorepo layout (backend/app, frontend/features, ...).
    if len(parts) > 2 and parts[0] in ("backend", "frontend", "src", "packages", "apps", "services"):
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _routes(file: IndexedFile) -> list[ApiRoute]:
    routes = []
    for number, line in enumerate(file.lines or [], start=1):
        match = _ROUTE.search(line)
        if match:
            routes.append(
                ApiRoute(file_path=file.path, line=number, method=match["method"].upper(), path=match["path"])
            )
    return routes


# --- architecture --------------------------------------------------------------------------------


def architecture(index: ProjectIndex) -> ArchitectureReport:
    roles: dict[str, FileRole] = {path: classify(file) for path, file in index.files.items()}
    by_component: dict[str, list[IndexedFile]] = {}
    for file in index.files.values():
        by_component.setdefault(_component(file.path), []).append(file)
    components = [
        Component(
            name=name,
            files=len(files),
            symbols=sum(len(f.symbols) for f in files),
            languages=dict(Counter(f.language.value for f in files).most_common()),
            roles=dict(Counter(roles[f.path].role for f in files).most_common()),
        )
        for name, files in sorted(by_component.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    link_counts: Counter[tuple[str, str]] = Counter()
    for source, targets in index.imports_of.items():
        for target in targets:
            a, b = _component(source), _component(target)
            if a != b:
                link_counts[(a, b)] += 1
    links = [ComponentLink(source=a, target=b, imports=n) for (a, b), n in link_counts.most_common()]
    routes = [r for f in index.files.values() if roles[f.path].role == "api_route" for r in _routes(f)]
    models = [
        f"{f.path}:{s.qualified_name}"
        for f in index.files.values()
        if roles[f.path].role == "data_model"
        for s in f.symbols
        if s.kind is SymbolKind.CLASS
    ]
    entry = sorted(
        f.path
        for f in index.files.values()
        if posixpath.basename(f.path) in _ENTRY_NAMES
        or posixpath.basename(f.path) in ("index.ts", "index.tsx")
    )
    truncated = any(len(x) > MAX_ITEMS for x in (components, links, routes, models, entry))
    return ArchitectureReport(
        files=len(index.files),
        languages=dict(Counter(f.language.value for f in index.files.values()).most_common()),
        roles=dict(Counter(r.role for r in roles.values()).most_common()),
        components=components[:MAX_ITEMS],
        links=links[:MAX_ITEMS],
        entry_points=entry[:MAX_ITEMS],
        api_routes=routes[:MAX_ITEMS],
        data_models=models[:MAX_ITEMS],
        tests=sum(1 for r in roles.values() if r.role == "test"),
        truncated=truncated,
        limitations=[
            "Roles come from file names, folders, and a few source markers; unusual layouts can be misread.",
            "Links are resolved imports between project files; HTTP calls (frontend to API) are not linked.",
            "No call graph or type analysis: functions are related through imports and names only.",
        ],
    )


# --- references and impact ------------------------------------------------------------------------


def _word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")


def _lines_with(file: IndexedFile, pattern: re.Pattern[str], skip: set[int] | None = None) -> list[int]:
    found = []
    for number, line in enumerate(file.lines or [], start=1):
        if skip and number in skip:
            continue
        if pattern.search(line):
            found.append(number)
    return found


def _definitions(
    index: ProjectIndex, name: str, file_path: str | None = None
) -> list[tuple[IndexedFile, CodeSymbol]]:
    files = [index.files[file_path]] if file_path else list(index.files.values())
    return [(f, s) for f in files for s in f.symbols if s.name == name or s.qualified_name == name]


def references(index: ProjectIndex, name: str) -> ReferenceReport:
    """Where a name is defined and where it is used, labelled confirmed or possible."""
    pattern = _word(name.split(".")[-1])
    definitions = _definitions(index, name)
    defining = {f.path for f, _ in definitions}
    role_of = _Roles(index)
    refs: list[Location] = []
    for file in index.files.values():
        own = {s.line for f, s in definitions if f.path == file.path}
        lines = _lines_with(file, pattern, own)
        if not lines:
            continue
        connected = file.path in defining or bool(index.imports_of.get(file.path, set()) & defining)
        refs.append(
            Location(
                file_path=file.path,
                lines=lines[:MAX_LINES_PER_FILE],
                relationship=CONFIRMED if connected else POSSIBLE,
                evidence="same file as the definition"
                if file.path in defining
                else "imports the defining file"
                if connected
                else "name occurs, but no import connects this file to a definition",
                role=role_of(file.path),
            )
        )
    refs.sort(key=lambda r: (r.relationship != CONFIRMED, r.file_path))
    return ReferenceReport(
        name=name,
        definitions=[
            Location(
                file_path=f.path,
                lines=[s.line],
                relationship=CONFIRMED,
                evidence=f"{s.kind.value} definition",
            )
            for f, s in definitions[:MAX_ITEMS]
        ],
        references=refs[:MAX_ITEMS],
        truncated=len(refs) > MAX_ITEMS or len(definitions) > MAX_ITEMS,
    )


def related_tests(index: ProjectIndex, file_path: str, role_of: _Roles | None = None) -> list[Location]:
    """Test files that import the file (confirmed) or whose name mentions it (possible)."""
    role_of = role_of or _Roles(index)
    stem = posixpath.splitext(posixpath.basename(file_path))[0].lower().removeprefix("test_")
    found: dict[str, Location] = {}
    for path in index.imported_by.get(file_path, set()):
        if role_of(path) == "test":
            found[path] = Location(
                file_path=path, relationship=CONFIRMED, evidence="imports the file", role="test"
            )
    if len(stem) >= MIN_POSSIBLE_NAME:
        for path in index.files:
            if path not in found and stem in posixpath.basename(path).lower() and role_of(path) == "test":
                found[path] = Location(
                    file_path=path, relationship=POSSIBLE, evidence="test file named after it", role="test"
                )
    return sorted(found.values(), key=lambda r: (r.relationship != CONFIRMED, r.file_path))[:MAX_ITEMS]


@dataclass
class _Reach:
    path: str
    chain: list[str]


def impact(index: ProjectIndex, file_path: str, symbol: str | None = None) -> ImpactReport:
    """What may be affected by changing ``file_path`` (or one ``symbol`` in it)."""
    target = index.files[file_path]
    role_of = _Roles(index)
    definitions = _definitions(index, symbol, file_path) if symbol else []
    name = symbol.split(".")[-1] if symbol else None
    pattern = _word(name) if name else None
    definition_lines = {s.line for _, s in definitions}

    direct: list[Location] = []
    for path in sorted(index.imported_by.get(file_path, set())):
        file = index.files[path]
        records = [r for r in file.imports if r.resolved_path == file_path]
        imported_names = {n for r in records for n in r.names}
        lines = _lines_with(file, pattern) if pattern else [r.line for r in records]
        if name and imported_names and name not in imported_names and "*" not in imported_names and not lines:
            continue  # imports other names from the file and never mentions this one
        evidence = (
            f"imports {name} from the file"
            if name and name in imported_names
            else f"imports the file and mentions {name}"
            if name and lines
            else "imports the file"
        )
        direct.append(
            Location(
                file_path=path,
                lines=lines[:MAX_LINES_PER_FILE],
                relationship=CONFIRMED,
                evidence=evidence,
                role=role_of(file.path),
            )
        )

    # Files reached through chains of resolved imports (breadth first, bounded depth).
    seen = {file_path, *(d.file_path for d in direct)}
    queue: deque[_Reach] = deque(_Reach(d.file_path, [file_path, d.file_path]) for d in direct)
    indirect: list[Location] = []
    while queue:
        reach = queue.popleft()
        if len(reach.chain) > MAX_DEPTH:
            continue
        for path in sorted(index.imported_by.get(reach.path, set())):
            if path in seen:
                continue
            seen.add(path)
            chain = [*reach.chain, path]
            indirect.append(
                Location(
                    file_path=path,
                    relationship=CONFIRMED,
                    evidence=f"imports {reach.path}, which depends on the target",
                    role=role_of(path),
                    chain=chain,
                )
            )
            queue.append(_Reach(path, chain))

    possible: list[Location] = []
    if pattern and name and len(name) >= MIN_POSSIBLE_NAME:
        for path, file in index.files.items():
            if path in seen:
                continue
            lines = _lines_with(file, pattern)
            if lines:
                possible.append(
                    Location(
                        file_path=path,
                        lines=lines[:MAX_LINES_PER_FILE],
                        relationship=POSSIBLE,
                        evidence=f"mentions {name}, but no import connects it to {file_path}",
                        role=role_of(file.path),
                    )
                )

    affected = [*direct, *indirect]
    tests = {t.file_path: t for t in related_tests(index, file_path, role_of)}
    for location in [*affected, *possible]:
        if location.role == "test" and location.file_path not in tests:
            tests[location.file_path] = location
    route_files = [index.files[loc.file_path] for loc in affected if loc.role == "api_route"]
    if role_of(file_path) == "api_route":
        route_files.insert(0, target)
    routes = [r for f in route_files for r in _routes(f)]

    own_imports = target.imports
    truncated = any(len(x) > MAX_ITEMS for x in (direct, indirect, possible, routes))
    return ImpactReport(
        file_path=file_path,
        symbol=symbol,
        definitions=[
            Location(
                file_path=file_path,
                lines=[s.line],
                relationship=CONFIRMED,
                evidence=f"{s.kind.value} definition",
            )
            for _, s in definitions
        ],
        same_file_references=_lines_with(target, pattern, definition_lines)[:MAX_ITEMS] if pattern else [],
        direct_dependents=direct[:MAX_ITEMS],
        indirect_dependents=indirect[:MAX_ITEMS],
        possible_references=possible[:MAX_ITEMS],
        dependencies=sorted(index.imports_of.get(file_path, set()))[:MAX_ITEMS],
        external_imports=sorted({r.module for r in own_imports if not r.resolved_path and r.module})[
            :MAX_ITEMS
        ],
        related_tests=sorted(tests.values(), key=lambda t: (t.relationship != CONFIRMED, t.file_path))[
            :MAX_ITEMS
        ],
        related_api_routes=routes[:MAX_ITEMS],
        truncated=truncated,
        limitations=[
            "Relationships come from resolved imports and identifier text; no call graph or type analysis.",
            "Possible references share the name only; they may refer to a different symbol.",
            "Dynamic imports, reflection, configuration-driven wiring, and HTTP calls are not followed.",
        ],
    )
