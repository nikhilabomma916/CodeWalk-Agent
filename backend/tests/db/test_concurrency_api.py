"""Concurrency (Module 14) on real PostgreSQL: parallel requests must keep data consistent.

Each worker uses its own TestClient (own connection and transaction) against the same app
and database, signed in as the same user, so requests really overlap in the database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import ActivityEvent, ActivityType, FileVersion
from app.services.ai.service import AIService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings
from tests.db.conftest import TEST_PASSWORD, register

WORKERS = 8


def clients_for(app: FastAPI, client_factory: Callable[[FastAPI], TestClient], n: int) -> list[TestClient]:
    first = client_factory(app)
    register(first)
    others = []
    for _ in range(n - 1):
        c = client_factory(app)
        assert (
            c.post(
                "/api/v1/auth/login", json={"email": "alice@example.com", "password": TEST_PASSWORD}
            ).status_code
            == 200
        )
        others.append(c)
    return [first, *others]


def test_parallel_saves_to_one_file_keep_versions_consistent(
    db_app: FastAPI, client_factory: Callable[[FastAPI], TestClient], engine: Engine
) -> None:
    clients = clients_for(db_app, client_factory, WORKERS)
    project = clients[0].post("/api/v1/projects", json={"name": "Race"}).json()
    file_id = (
        clients[0]
        .post(f"/api/v1/projects/{project['id']}/files", json={"path": "a.py", "content": "x = 0\n"})
        .json()["file"]["id"]
    )

    def save(i: int) -> int:
        response = clients[i].patch(
            f"/api/v1/projects/{project['id']}/files/{file_id}", json={"content": f"x = {i + 1}\n"}
        )
        return response.status_code

    with ThreadPoolExecutor(WORKERS) as pool:
        statuses = list(pool.map(save, range(WORKERS)))
    assert all(s in (200, 409) for s in statuses), statuses  # never a 500
    assert statuses.count(200) >= 1
    with Session(engine) as session:
        versions = session.scalars(
            select(FileVersion.version).where(FileVersion.file_id == file_id).order_by(FileVersion.version)
        ).all()
    assert versions == list(range(1, len(versions) + 1))  # unique and gap-free
    assert len(versions) == 1 + statuses.count(200)
    final = clients[0].get(f"/api/v1/projects/{project['id']}/files/{file_id}").json()["content"]
    assert final in {f"x = {i + 1}\n" for i in range(WORKERS)}


def test_parallel_reads_searches_and_analyses(
    db_app: FastAPI, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    clients = clients_for(db_app, client_factory, WORKERS)
    project = clients[0].post("/api/v1/projects", json={"name": "Busy"}).json()
    for i in range(10):
        clients[0].post(
            f"/api/v1/projects/{project['id']}/files",
            json={"path": f"pkg/mod{i}.py", "content": f"def handler_{i}(x):\n    return x + {i}\n"},
        )

    def work(i: int) -> list[int]:
        c = clients[i]
        return [
            c.post(
                f"/api/v1/projects/{project['id']}/search", json={"query": f"handler_{i % 10}"}
            ).status_code,
            c.post("/api/v1/analysis/code", json={"code": "def f(:\n", "language": "python"}).status_code,
            c.post(f"/api/v1/projects/{project['id']}/analyze").status_code,
            c.get(f"/api/v1/projects/{project['id']}/files").status_code,
        ]

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(work, range(WORKERS)))
    assert all(code == 200 for row in results for code in row), results


def test_simultaneous_approvals_apply_a_proposal_once(
    database_url: str, workspace: Any, client_factory: Callable[[FastAPI], TestClient], engine: Engine
) -> None:
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    edits = [{"start_line": 2, "end_line": 2, "replacement": "    total = 0\n    for item in items:"}]
    stub = StubProvider(
        answers=[
            {
                "status_message": "Proposing",
                "action": "call_tool",
                "tool": "propose_fix",
                "arguments_json": json.dumps(
                    {"file_path": "cart.py", "summary": "init total", "explanation": "x", "edits": edits}
                ),
                "answer": None,
            },
            {
                "status_message": "Done",
                "action": "answer",
                "tool": None,
                "arguments_json": None,
                "answer": "ok",
            },
        ]
    )
    app.state.ai_service = AIService(make_settings(ai_enabled=True, database_url=database_url), provider=stub)
    clients = clients_for(app, client_factory, WORKERS)
    project = clients[0].post("/api/v1/projects", json={"name": "Approve race"}).json()
    code = "def total(items):\n    for item in items:\n        total += item\n    return total\n"
    clients[0].post(f"/api/v1/projects/{project['id']}/files", json={"path": "cart.py", "content": code})
    run = clients[0].post("/api/v1/agent/run", json={"project_id": project["id"], "message": "fix"}).json()
    action_id = run["actions"][0]["id"]

    def approve(i: int) -> int:
        return clients[i].post(f"/api/v1/agent/actions/{action_id}/approve").status_code

    with ThreadPoolExecutor(WORKERS) as pool:
        statuses = list(pool.map(approve, range(WORKERS)))
    assert statuses.count(200) == 1, statuses
    assert all(s == 409 for s in statuses if s != 200), statuses
    with Session(engine) as session:
        applied = session.scalar(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.event_type == ActivityType.AGENT_ACTION_APPLIED)
        )
        versions = session.scalar(select(func.count()).select_from(FileVersion))
    assert applied == 1
    assert versions == 2  # the original and exactly one applied change
