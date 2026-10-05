"""Module 16 unit tests: atomic rate limiting, incremental search-index assembly, vector text
encoding, and bounded metrics. No database is needed."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.metrics import MAX_SERIES, Metrics
from app.core.rate_limit import AttemptLimiter
from app.db.vector import from_text, to_text
from app.services.file_content import content_hash
from app.services.languages import detect_language
from app.services.project_intelligence.models import (
    FileStructure,
    ProjectSummary,
    RelationshipKind,
    SourceFile,
    TargetKind,
)
from app.services.project_intelligence.project_analyzer import (
    STRUCTURE_LANGUAGES,
    analyze_project,
    extract_structure,
)
from app.services.project_search.index import LoadedFile, ProjectIndex
from tests.conftest import build_app

# --- rate limiting -------------------------------------------------------------------------------


def test_acquire_admits_exactly_the_limit_under_concurrency() -> None:
    limiter = AttemptLimiter(max_attempts=3, window_seconds=60)
    start = threading.Barrier(32)

    def attempt(_: int) -> int | None:
        start.wait()
        return limiter.acquire("agent:user")

    with ThreadPoolExecutor(32) as pool:
        results = list(pool.map(attempt, range(32)))
    assert results.count(None) == 3
    assert all(isinstance(r, int) and r >= 1 for r in results if r is not None)


def test_acquire_counts_only_admitted_attempts_and_reset_clears() -> None:
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60)
    assert limiter.acquire("k") is None
    assert limiter.acquire("k") is None
    assert limiter.acquire("k") is not None  # refused, and not recorded
    assert limiter.retry_after("k") is not None
    limiter.reset("k")
    assert limiter.acquire("k") is None
    assert limiter.acquire("other") is None  # keys are independent


# --- incremental search index ----------------------------------------------------------------------

BASE_FILES = {
    "app/__init__.py": "",
    "app/db.py": "def connect(url):\n    return url\n",
    "app/users.py": (
        "from app.db import connect\nfrom app import missing_mod\n\n\ndef find(e):\n    return connect(e)\n"
    ),
    "web/tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@lib/*": ["lib/*"]}}}',
    "web/lib/api.ts": "export function call() { return 1; }\n",
    "web/main.ts": "import { call } from '@lib/api';\nimport { x } from './later';\ncall();\n",
    "node_modules/pkg/index.js": "module.exports = 1;\n",
    ".env": "SECRET=1\n",
    "README.md": "# readme\n",
}


def loaded(path: str, content: str) -> LoadedFile:
    language = detect_language(path)
    structure = FileStructure()
    if language in STRUCTURE_LANGUAGES:
        structure = extract_structure(SourceFile(path=path, size=len(content), content=content), language)
    return LoadedFile(path=path, content_hash=content_hash(content), content=content, structure=structure)


def full_index(files: dict[str, str]) -> ProjectIndex:
    ordered = dict(sorted(files.items()))
    return ProjectIndex.assemble(
        {p: content_hash(c) for p, c in ordered.items()}, {p: loaded(p, c) for p, c in ordered.items()}
    )


def snapshot(index: ProjectIndex) -> dict[str, object]:
    return {
        "files": {
            path: (
                file.name,
                file.language,
                file.lines,
                [s.model_dump() for s in file.symbols],
                [r.model_dump() for r in file.imports],
            )
            for path, file in index.files.items()
        },
        "imports_of": index.imports_of,
        "imported_by": index.imported_by,
        "hashes": index.hashes,
    }


def test_full_assembly_matches_project_intelligence_relationships() -> None:
    """The index resolves imports exactly like project intelligence (the previous index source)."""
    index = full_index(BASE_FILES)
    files = [SourceFile(path=p, size=len(c), content=c) for p, c in sorted(BASE_FILES.items())]
    result = analyze_project(project=ProjectSummary(id="p", name="p", root_path=None), files=files)
    expected: dict[str, set[str]] = {}
    for rel in result.relationships:
        internal = rel.kind is RelationshipKind.IMPORTS and rel.target_kind is TargetKind.FILE
        if internal and rel.source in index.files and rel.target in index.files:
            expected.setdefault(rel.source, set()).add(rel.target)
    assert index.imports_of == expected
    assert index.imports_of["web/main.ts"] == {"web/lib/api.ts"}  # tsconfig path alias
    assert "node_modules/pkg/index.js" not in index.files
    assert ".env" not in index.files
    resolved = {info.path: [r.resolved_path for r in info.imports] for info in result.files}
    for path, file in index.files.items():
        assert [r.resolved_path for r in file.imports] == resolved[path]


@pytest.mark.parametrize(
    "change",
    ["edit", "add_import_target", "delete_import_target", "edit_tsconfig", "rename"],
)
def test_incremental_assembly_equals_a_full_rebuild(change: str) -> None:
    before = full_index(BASE_FILES)
    after = dict(BASE_FILES)
    if change == "edit":
        after["app/db.py"] = "def connect(url, timeout=1):\n    return url\n\n\ndef close():\n    pass\n"
    elif change == "add_import_target":
        after["web/later.ts"] = "export const x = 1;\n"  # main.ts's './later' import now resolves
        after["app/missing_mod.py"] = "VALUE = 1\n"
    elif change == "delete_import_target":
        del after["app/db.py"]
    elif change == "edit_tsconfig":
        after["web/tsconfig.json"] = '{"compilerOptions": {"baseUrl": "."}}'  # alias removed
    else:
        after["app/database.py"] = after.pop("app/db.py")
    ordered = dict(sorted(after.items()))
    hashes = {p: content_hash(c) for p, c in ordered.items()}
    stale = before.stale_paths(hashes)
    incremental = ProjectIndex.assemble(hashes, {p: loaded(p, ordered[p]) for p in stale}, before)
    assert snapshot(incremental) == snapshot(full_index(after))
    unchanged = [p for p in incremental.files if p not in stale and p in before.files]
    assert unchanged
    assert all(incremental.files[p].lines is before.files[p].lines for p in unchanged)


def test_incremental_assembly_never_mutates_the_previous_index() -> None:
    before = full_index(BASE_FILES)
    resolved_before = [r.resolved_path for r in before.files["web/main.ts"].imports]
    after = {**BASE_FILES, "web/later.ts": "export const x = 1;\n"}
    hashes = {p: content_hash(c) for p, c in sorted(after.items())}
    new = ProjectIndex.assemble(
        hashes, {"web/later.ts": loaded("web/later.ts", after["web/later.ts"])}, before
    )
    assert [r.resolved_path for r in before.files["web/main.ts"].imports] == resolved_before
    assert [r.resolved_path for r in new.files["web/main.ts"].imports] == ["web/lib/api.ts", "web/later.ts"]


# --- vector text form ------------------------------------------------------------------------------


def test_vector_text_round_trip() -> None:
    values = [0.1, -2.5e-07, 3.0, 1e20, 0.0]
    assert to_text(values) == "[0.1,-2.5e-07,3.0,1e+20,0.0]"
    assert from_text(to_text(values)) == values
    assert from_text("[1,2.5]") == [1.0, 2.5]


# --- metrics ---------------------------------------------------------------------------------------


def test_metrics_endpoint_uses_route_templates_and_no_user_data() -> None:
    app = build_app()
    with TestClient(app) as client:
        client.get("/api/v1/health/live")
        client.get("/api/v1/projects/3fa85f64-5717-4562-b3fc-2c963f66afa6?email=secret@example.com")
        client.post("/api/v1/analysis/code", json={"code": "x = 1\n", "language": "python"})
        body = client.get("/metrics").text
    assert 'route="/api/v1/health/live"' in body
    assert 'route="/api/v1/projects/{project_id}"' in body
    assert 'operation="code_analysis",outcome="ok"' in body
    assert "3fa85f64" not in body
    assert "secret@example.com" not in body
    assert "codewalk_http_request_duration_seconds_count" in body


def test_metrics_can_be_disabled() -> None:
    with TestClient(build_app(metrics_enabled=False)) as client:
        assert client.get("/metrics").status_code == 404


def test_metric_series_are_capped() -> None:
    metrics = Metrics()
    for i in range(MAX_SERIES + 50):
        metrics.observe(f"op{i}", 0.01)
    text = metrics.render()
    assert text.count("codewalk_operation_duration_seconds_count") == MAX_SERIES + 1
    assert 'operation="_other"' in text
