"""Module 16 on real PostgreSQL: concurrency limits, approval races, the incremental search index,
batched indexing and folder sync, semantic search without wasted work, indexes, and timeouts."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import FileVersion, FileVersionSource
from app.db.session import Database
from app.repositories.files import FileRepository
from app.services.ai.service import AIService
from app.services.project_search.service import ProjectSearchService
from app.services.retrieval.service import RetrievalService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings
from tests.db.conftest import TEST_PASSWORD, register
from tests.embedding_stub import StubEmbeddingProvider

WORKERS = 8
API = "/api/v1"


def signed_in_clients(
    app: FastAPI, client_factory: Callable[[FastAPI], TestClient], n: int
) -> list[TestClient]:
    first = client_factory(app)
    register(first)
    clients = [first]
    for _ in range(n - 1):
        c = client_factory(app)
        login = c.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": TEST_PASSWORD})
        assert login.status_code == 200
        clients.append(c)
    return clients


def answer() -> dict[str, Any]:
    return {
        "status_message": "Done",
        "action": "answer",
        "tool": None,
        "arguments_json": None,
        "answer": "ok",
    }


def propose(replacement: str) -> list[dict[str, Any]]:
    edits = [{"start_line": 2, "end_line": 2, "replacement": replacement}]
    return [
        {
            "status_message": "Proposing",
            "action": "call_tool",
            "tool": "propose_fix",
            "arguments_json": json.dumps(
                {"file_path": "cart.py", "summary": "change", "explanation": "x", "edits": edits}
            ),
            "answer": None,
        },
        answer(),
    ]


CART = "def total(items):\n    for item in items:\n        total += item\n    return total\n"


# --- concurrency -----------------------------------------------------------------------------------


def test_simultaneous_agent_runs_cannot_exceed_the_run_limit(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app = build_app(
        database_url=database_url, workspace_root=str(workspace), ai_enabled=True, agent_max_runs=2
    )
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url),
        provider=StubProvider(answers=[answer() for _ in range(WORKERS)]),
    )
    clients = signed_in_clients(app, client_factory, WORKERS)
    project = clients[0].post(f"{API}/projects", json={"name": "Limits"}).json()

    def run(i: int) -> int:
        return (
            clients[i]
            .post(f"{API}/agent/run", json={"project_id": project["id"], "message": "hi"})
            .status_code
        )

    with ThreadPoolExecutor(WORKERS) as pool:
        statuses = list(pool.map(run, range(WORKERS)))
    assert statuses.count(200) == 2, statuses
    assert statuses.count(429) == WORKERS - 2, statuses


def test_different_proposals_for_one_file_cannot_both_apply(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient], engine: Engine
) -> None:
    """Two proposals computed against the same content, approved at the same time: one is applied,
    the other is reported stale; the first change is never silently overwritten."""
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    stub = StubProvider()
    app.state.ai_service = AIService(make_settings(ai_enabled=True, database_url=database_url), provider=stub)
    clients = signed_in_clients(app, client_factory, 2)
    project = clients[0].post(f"{API}/projects", json={"name": "Two proposals"}).json()
    file_id = (
        clients[0]
        .post(f"{API}/projects/{project['id']}/files", json={"path": "cart.py", "content": CART})
        .json()["file"]["id"]
    )

    def two_proposals() -> list[str]:
        actions = []
        for value in (0, 100):
            stub.answers.extend(propose(f"    total = {value}\n    for item in items:"))
            body = {"project_id": project["id"], "message": "fix"}
            actions.append(clients[0].post(f"{API}/agent/run", json=body).json()["actions"][0]["id"])
        return actions

    def approve_together(actions: list[str]) -> list[int]:
        def approve(i: int) -> int:
            return clients[i].post(f"{API}/agent/actions/{actions[i]}/approve").status_code

        with ThreadPoolExecutor(2) as pool:
            return sorted(pool.map(approve, range(2)))

    for _ in range(5):  # repeated: the race window is small
        statuses = approve_together(two_proposals())
        assert statuses == [200, 409], statuses
        content = clients[0].get(f"{API}/projects/{project['id']}/files/{file_id}").json()["content"]
        assert content.count("total = ") == 1  # exactly one change applied, on the original content
        # Restore the original for the next round.
        clients[0].patch(f"{API}/projects/{project['id']}/files/{file_id}", json={"content": CART})


# --- incremental project index ---------------------------------------------------------------------


def test_search_after_an_edit_reloads_only_the_changed_file(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = api.post(f"{API}/projects", json={"name": "Incremental"}).json()
    ids = {}
    for i in range(6):
        previous = max(i - 1, 0)
        content = f"from pkg.m{previous} import f{previous}\n\n\ndef f{i}():\n    return {i}\n"
        response = api.post(
            f"{API}/projects/{project['id']}/files", json={"path": f"pkg/m{i}.py", "content": content}
        )
        ids[i] = response.json()["file"]["id"]
    assert api.post(f"{API}/projects/{project['id']}/search", json={"query": "f3"}).json()["total"] >= 1

    calls: dict[str, list[Any]] = {"all": [], "paths": []}
    list_all, list_by_paths = FileRepository.list_all, FileRepository.list_by_paths

    def spy_all(self: FileRepository, project_id: Any) -> Any:
        calls["all"].append(project_id)
        return list_all(self, project_id)

    def spy_paths(self: FileRepository, project_id: Any, paths: Any) -> Any:
        calls["paths"].append(list(paths))
        return list_by_paths(self, project_id, paths)

    monkeypatch.setattr(FileRepository, "list_all", spy_all)
    monkeypatch.setattr(FileRepository, "list_by_paths", spy_paths)
    api.patch(
        f"{API}/projects/{project['id']}/files/{ids[2]}",
        json={"content": "from pkg.m1 import f1\n\n\ndef renamed_helper():\n    return 2\n"},
    )
    body = api.post(f"{API}/projects/{project['id']}/search", json={"query": "renamed_helper"}).json()
    assert [r["file_path"] for r in body["results"] if r["match_type"] == "symbol_exact"] == ["pkg/m2.py"]
    assert calls == {"all": [], "paths": [["pkg/m2.py"]]}
    gone = api.post(f"{API}/projects/{project['id']}/search", json={"query": "f2"}).json()
    assert not [r for r in gone["results"] if r["symbol_name"] == "f2"]

    # Import relationships follow the change: m3 imports m2, so m2's context lists m3 as an importer.
    context = api.post(f"{API}/projects/{project['id']}/context", json={"current_file": "pkg/m2.py"}).json()
    assert "pkg/m3.py" in json.dumps(context)


# --- semantic search does no wasted deterministic work ---------------------------------------------


def test_semantic_mode_skips_deterministic_matching_unless_it_falls_back(
    database_url: str, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(database_url=database_url, workspace_root=str(workspace), rag_enabled=True)
    app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=StubEmbeddingProvider()
    )
    matched: list[str] = []
    original = ProjectSearchService._match_file

    def spy(self: ProjectSearchService, file: Any, *args: Any) -> Any:
        matched.append(file.path)
        return original(self, file, *args)

    monkeypatch.setattr(ProjectSearchService, "_match_file", spy)
    with TestClient(app) as client:
        register(client)
        project = client.post(f"{API}/projects", json={"name": "Semantic"}).json()
        client.post(
            f"{API}/projects/{project['id']}/files",
            json={"path": "pay.py", "content": "def charge_card(amount):\n    return amount * 2\n"},
        )
        assert client.post(f"{API}/projects/{project['id']}/rag/index").status_code == 200
        search = f"{API}/projects/{project['id']}/search"
        semantic = client.post(search, json={"query": "charge card", "mode": "semantic"}).json()
        assert semantic["mode_used"] == "semantic"
        assert semantic["results"]
        assert matched == []
        hybrid = client.post(search, json={"query": "charge card", "mode": "hybrid"}).json()
        assert hybrid["mode_used"] == "hybrid"
        assert matched == ["pay.py"]
        matched.clear()
        # Semantic retrieval unavailable: the response falls back to deterministic matching.
        app.state.retrieval_service.provider.configured = False
        fallback = client.post(search, json={"query": "charge_card", "mode": "semantic"}).json()
        assert fallback["mode_used"] == "deterministic"
        assert fallback["results"]
        assert matched == ["pay.py"]


def test_indexing_statements_do_not_grow_per_file(database_url: str, workspace: Path, engine: Engine) -> None:
    app = build_app(database_url=database_url, workspace_root=str(workspace), rag_enabled=True)
    app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=StubEmbeddingProvider()
    )
    statements = {"n": 0}

    def count(*_: Any) -> None:
        statements["n"] += 1

    with TestClient(app) as client:
        register(client)
        project = client.post(f"{API}/projects", json={"name": "Batch"}).json()
        for i in range(40):
            client.post(
                f"{API}/projects/{project['id']}/files",
                json={"path": f"m{i}.py", "content": f"def f{i}(x):\n    return x + {i}\n"},
            )
        client.post(f"{API}/projects/{project['id']}/search", json={"query": "warm"})
        event.listen(app.state.database.engine, "before_cursor_execute", count)
        try:
            body = client.post(f"{API}/projects/{project['id']}/rag/index").json()
        finally:
            event.remove(app.state.database.engine, "before_cursor_execute", count)
    assert body["files_indexed"] == 40
    assert body["chunks_embedded"] == 40
    assert statements["n"] < 20, statements  # was about two statements per file
    with Session(engine) as session:
        assert session.scalar(text("SELECT count(*) FROM code_chunks")) == 40


# --- folder sync -----------------------------------------------------------------------------------


def test_folder_import_creates_first_versions_in_one_batch(
    api: TestClient, workspace: Path, engine: Engine
) -> None:
    folder = workspace / "repo"
    for i in range(30):
        (folder / "src").mkdir(parents=True, exist_ok=True)
        (folder / "src" / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    (folder / "node_modules").mkdir()
    (folder / "node_modules" / "x.js").write_text("1\n", encoding="utf-8")
    project = api.post(f"{API}/projects", json={"name": "Repo", "root_path": "repo"}).json()
    body = api.post(f"{API}/projects/{project['id']}/analyze").json()
    assert body["sync"] == {"created": 30, "updated": 0, "deleted": 0, "unchanged": 0}
    with Session(engine) as session:
        versions = session.execute(
            select(FileVersion.version, FileVersion.source, FileVersion.author_id)
        ).all()
    assert len(versions) == 30
    assert {(v, s, a) for v, s, a in versions} == {(1, FileVersionSource.SCAN, None)}
    # A rescan after an edit on disk records version 2 for that file only.
    (folder / "src" / "m3.py").write_text("def f3():\n    return 33\n", encoding="utf-8")
    body = api.post(f"{API}/projects/{project['id']}/analyze").json()
    assert body["sync"] == {"created": 0, "updated": 1, "deleted": 0, "unchanged": 29}
    with Session(engine) as session:
        assert session.scalar(select(func.max(FileVersion.version))) == 2
        assert session.scalar(select(func.count()).select_from(FileVersion)) == 31


# --- schema and database settings ------------------------------------------------------------------


def test_activity_reference_indexes_exist_and_are_partial(engine: Engine) -> None:
    indexes = {i["name"]: i for i in inspect(engine).get_indexes("activity_events")}
    assert indexes["ix_activity_events_file_id"]["column_names"] == ["file_id"]
    assert indexes["ix_activity_events_analysis_id"]["column_names"] == ["analysis_id"]
    with engine.connect() as connection:
        predicates: dict[str, str] = dict(
            connection.execute(
                text(
                    "SELECT c.relname, pg_get_expr(i.indpred, i.indrelid) FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname IN ('ix_activity_events_file_id', 'ix_activity_events_analysis_id')"
                )
            ).all()
        )
        valid: bool = connection.execute(
            text(
                "SELECT bool_and(i.indisvalid) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname LIKE 'ix_activity_events_%'"
            )
        ).scalar_one()
    assert predicates == {
        "ix_activity_events_file_id": "(file_id IS NOT NULL)",
        "ix_activity_events_analysis_id": "(analysis_id IS NOT NULL)",
    }
    assert valid is True


def test_statement_timeout_applies_to_application_connections(database_url: str) -> None:
    database = Database(database_url, pool_size=1, statement_timeout_seconds=1.5)
    try:
        with database.session() as session:
            assert session.execute(text("SHOW statement_timeout")).scalar_one() == "1500ms"
            with pytest.raises(Exception, match="statement timeout"):
                session.execute(text("SELECT pg_sleep(3)"))
    finally:
        database.dispose()
    default = Database.from_settings(make_settings(database_url=database_url))
    assert default is not None
    try:
        with default.session() as session:
            assert session.execute(text("SHOW statement_timeout")).scalar_one() == "30s"
    finally:
        default.dispose()


def test_exact_match_in_a_late_file_is_not_lost_in_a_large_project(api: TestClient, workspace: Path) -> None:
    """More than 1,000 weaker matches come before the defining file in path order; the exact match
    must still rank first (it used to be dropped when collection stopped at 1,000 candidates)."""
    folder = workspace / "big"
    (folder / "pkg").mkdir(parents=True)
    for i in range(400):
        body = "".join(f"\ndef func_{i}_{j}(value):\n    return value + {j}\n" for j in range(5))
        (folder / "pkg" / f"mod{i}.py").write_text(body, encoding="utf-8")
    project = api.post(f"{API}/projects", json={"name": "Big", "root_path": "big"}).json()
    assert api.post(f"{API}/projects/{project['id']}/analyze").status_code == 200
    body = api.post(f"{API}/projects/{project['id']}/search", json={"query": "func_399_3"}).json()
    top = body["results"][0]
    assert (top["file_path"], top["qualified_name"], top["match_type"]) == (
        "pkg/mod399.py",
        "func_399_3",
        "symbol_exact",
    )
    assert body["total"] == 1000
    assert body["truncated"] is True
