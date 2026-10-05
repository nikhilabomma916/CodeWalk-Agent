"""Production validation (Module 14): data lifecycle on real PostgreSQL.

- Upgrading a populated database from an older schema keeps every row.
- Deleting a user removes everything they own, across all modules' tables.
- Timestamps are set by the database and move on updates.
- Per-user rate limits do not leak between users.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from alembic import command
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import (
    ActivityEvent,
    AgentAction,
    AgentRun,
    Analysis,
    AuthSession,
    CodeChunk,
    DiagnosticRecord,
    FileVersion,
    Project,
    ProjectFile,
    ProjectOrigin,
    User,
)
from app.services.ai.service import AIService
from app.services.file_content import file_values
from app.services.retrieval.service import RetrievalService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings
from tests.db.conftest import alembic_config, register
from tests.embedding_stub import StubEmbeddingProvider

PRE_PGVECTOR = "aa335eec9810"  # Modules 7-9 schema: before code_chunks and the agent tables


def test_upgrading_a_populated_database_keeps_its_data(database_url: str, engine: Engine) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, PRE_PGVECTOR)
    try:
        assert "code_chunks" not in inspect(engine).get_table_names()
        with Session(engine) as session:
            user = User(email="legacy@example.com", name="Legacy", password_hash="x")
            session.add(user)
            session.flush()
            # Inserted with the old schema's columns only (the current model has columns added later).
            project_id = uuid.uuid4()
            session.execute(
                text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Legacy project')"),
                {"id": project_id, "owner": user.id},
            )
            session.add(ProjectFile(project_id=project_id, **file_values("app.py", "print('kept')\n")))
            session.commit()
            ids = (user.id, project_id)
    finally:
        command.upgrade(config, "head")
    tables = set(inspect(engine).get_table_names())
    assert {"code_chunks", "agent_runs", "agent_actions"} <= tables
    with Session(engine) as session:
        assert session.get(User, ids[0]) is not None
        legacy = session.get(Project, ids[1])
        assert legacy is not None
        assert legacy.origin is ProjectOrigin.WORKSPACE  # existing projects stay in the workspace
        stored = session.scalar(select(ProjectFile.content).where(ProjectFile.project_id == ids[1]))
        assert stored == "print('kept')\n"
        version: str = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == ScriptDirectory.from_config(config).get_current_head()
        assert session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar() == 1


def _everything(session: Session, user_id: Any) -> dict[str, int]:
    project_ids = select(Project.id).where(Project.owner_id == user_id)
    file_ids = select(ProjectFile.id).where(ProjectFile.project_id.in_(project_ids))
    analysis_ids = select(Analysis.id).where(Analysis.project_id.in_(project_ids))
    counts = {
        "auth_sessions": select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id),
        "projects": select(func.count()).select_from(Project).where(Project.owner_id == user_id),
        "files": select(func.count()).select_from(ProjectFile).where(ProjectFile.project_id.in_(project_ids)),
        "file_versions": select(func.count())
        .select_from(FileVersion)
        .where(FileVersion.file_id.in_(file_ids)),
        "analyses": select(func.count()).select_from(Analysis).where(Analysis.project_id.in_(project_ids)),
        "diagnostics": select(func.count())
        .select_from(DiagnosticRecord)
        .where(DiagnosticRecord.analysis_id.in_(analysis_ids)),
        "activity_events": select(func.count())
        .select_from(ActivityEvent)
        .where(ActivityEvent.user_id == user_id),
        "code_chunks": select(func.count())
        .select_from(CodeChunk)
        .where(CodeChunk.project_id.in_(project_ids)),
        "agent_runs": select(func.count()).select_from(AgentRun).where(AgentRun.user_id == user_id),
        "agent_actions": select(func.count()).select_from(AgentAction).where(AgentAction.user_id == user_id),
    }
    return {name: int(session.scalar(query) or 0) for name, query in counts.items()}


def test_deleting_a_user_removes_everything_they_own(
    database_url: str, workspace: Any, client_factory: Callable[[FastAPI], TestClient], engine: Engine
) -> None:
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    edits = [{"start_line": 1, "end_line": 1, "replacement": "x = 2"}]
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url),
        provider=StubProvider(
            answers=[
                {
                    "status_message": "p",
                    "action": "call_tool",
                    "tool": "propose_fix",
                    "arguments_json": json.dumps(
                        {"file_path": "a.py", "summary": "s", "explanation": "e", "edits": edits}
                    ),
                    "answer": None,
                },
                {
                    "status_message": "a",
                    "action": "answer",
                    "tool": None,
                    "arguments_json": None,
                    "answer": "ok",
                },
            ]
        ),
    )
    app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=StubEmbeddingProvider()
    )
    alice, bob = client_factory(app), client_factory(app)
    alice_id = register(alice)["id"]
    bob_id = register(bob, email="bob@example.com", name="Bob")["id"]
    for client in (alice, bob):
        pid = client.post("/api/v1/projects", json={"name": "Owned"}).json()["id"]
        client.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "x = 1\nprint(y)\n"})
        client.post(f"/api/v1/projects/{pid}/rag/index")
    pid = alice.get("/api/v1/projects").json()["items"][0]["id"]
    assert alice.post("/api/v1/agent/run", json={"project_id": pid, "message": "fix"}).json()["actions"]

    with Session(engine) as session:
        before = _everything(session, alice_id)
        assert all(count > 0 for count in before.values()), before
        bob_before = _everything(session, bob_id)
        session.execute(delete(User).where(User.id == alice_id))
        session.commit()
        after = _everything(session, alice_id)
        assert set(after.values()) == {0}, after
        assert _everything(session, bob_id) == bob_before  # nobody else is affected


def test_timestamps_come_from_the_database(api: TestClient, engine: Engine) -> None:
    project = api.post("/api/v1/projects", json={"name": "Times"}).json()
    created = api.post(f"/api/v1/projects/{project['id']}/files", json={"path": "t.py", "content": "a = 1\n"})
    file = created.json()["file"]
    time.sleep(1.1)
    response = api.patch(f"/api/v1/projects/{project['id']}/files/{file['id']}", json={"content": "a = 2\n"})
    assert response.status_code == 200
    with Session(engine) as session:
        row = session.get(ProjectFile, file["id"])
        assert row is not None
        assert row.created_at.tzinfo is not None
        assert row.updated_at > row.created_at


def test_rate_limits_are_per_user(
    database_url: str, workspace: Any, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app = build_app(
        database_url=database_url, workspace_root=str(workspace), ai_enabled=True, agent_max_runs=1
    )
    answer = {"status_message": "a", "action": "answer", "tool": None, "arguments_json": None, "answer": "ok"}
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url),
        provider=StubProvider(answers=[answer, answer]),
    )
    alice, bob = client_factory(app), client_factory(app)
    register(alice)
    register(bob, email="bob@example.com", name="Bob")
    a_pid = alice.post("/api/v1/projects", json={"name": "A"}).json()["id"]
    b_pid = bob.post("/api/v1/projects", json={"name": "B"}).json()["id"]
    assert alice.post("/api/v1/agent/run", json={"project_id": a_pid, "message": "q"}).status_code == 200
    limited = alice.post("/api/v1/agent/run", json={"project_id": a_pid, "message": "q"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    # Alice's limit does not touch Bob.
    assert bob.post("/api/v1/agent/run", json={"project_id": b_pid, "message": "q"}).status_code == 200
