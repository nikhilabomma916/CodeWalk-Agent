"""Uploaded projects (Module 18): ``origin`` separates them from workspace projects, and the agent
analyzes them read-only (it answers, but cannot propose changes)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import AgentAction
from tests.db.test_agent_api import FILES, FIX_EDITS, UNDEFINED, answer, make_client, tool

__all__ = ["make_client"]  # the fixture is used by name below


def test_projects_are_listed_by_origin(api: TestClient) -> None:
    workspace = api.post("/api/v1/projects", json={"name": "Workspace"}).json()
    upload = api.post("/api/v1/projects", json={"name": "Laptop", "origin": "upload"}).json()
    assert workspace["origin"] == "workspace"
    assert upload["origin"] == "upload"

    def names(query: str) -> list[str]:
        response = api.get(f"/api/v1/projects{query}")
        assert response.status_code == 200, response.text
        return sorted(p["name"] for p in response.json()["items"])

    assert names("") == ["Laptop", "Workspace"]
    assert names("?origin=workspace") == ["Workspace"]
    assert names("?origin=upload") == ["Laptop"]
    assert api.get("/api/v1/projects?origin=other").status_code == 422
    assert api.get(f"/api/v1/projects/{upload['id']}").json()["origin"] == "upload"


def test_an_upload_cannot_be_linked_to_a_server_folder(api: TestClient, workspace: Path) -> None:
    (workspace / "linked").mkdir()
    response = api.post("/api/v1/projects", json={"name": "X", "origin": "upload", "root_path": "linked"})
    assert response.status_code == 422


def test_the_agent_only_answers_on_uploaded_projects(make_client: Callable[..., Any], engine: Engine) -> None:
    client, _, _ = make_client(
        tool(
            "propose_fix",
            file_path="shop/cart.py",
            summary="Initialize total",
            explanation="total is used before assignment.",
            edits=FIX_EDITS,
        ),
        answer("total is used before it is assigned; initialize it to 0 before the loop."),
    )
    project = client.post("/api/v1/projects", json={"name": "Laptop", "origin": "upload"}).json()
    imported = client.post(
        f"/api/v1/projects/{project['id']}/files/import",
        json={"files": [{"path": path, "content": content} for path, content in FILES.items()]},
    )
    assert imported.status_code == 200, imported.text

    response = client.post(
        "/api/v1/agent/run",
        json={
            "project_id": project["id"],
            "message": "Why is total undefined?",
            "file_path": "shop/cart.py",
            "diagnostics": [UNDEFINED],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["answer"].startswith("total is used")
    assert [(c["tool"], c["status"], c["error_code"]) for c in body["tool_calls"]] == [
        ("propose_fix", "denied", "read_only_project")
    ]
    assert body["actions"] == []
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AgentAction)) == 0
