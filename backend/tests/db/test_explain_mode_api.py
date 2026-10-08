"""Project explanation (mode "explain"): one topic at a chosen depth, grounded in the project's files
through the read-only tools. The workflow only answers: proposal tools are denied even on a workspace
project, and nothing is stored as a change."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import AgentAction, AgentRun
from tests.db.test_agent_api import FIX_EDITS, answer, make_client, make_project, tool

__all__ = ["make_client"]  # the fixture is used by name below


def test_explain_reads_the_project_and_never_proposes(
    make_client: Callable[..., Any], engine: Engine
) -> None:
    client, provider, _ = make_client(
        tool("get_architecture"),
        tool("get_file_content", file_path="shop/cart.py"),
        tool(
            "propose_fix",
            file_path="shop/cart.py",
            summary="Initialize total",
            explanation="total is used before assignment.",
            edits=FIX_EDITS,
        ),
        answer("## Data flow\nItems go through shop/cart.py:1 ..."),
    )
    project_id = make_project(client)["id"]

    response = client.post(
        "/api/v1/agent/run",
        json={
            "project_id": project_id,
            "message": "Explain the data flow.",
            "mode": "explain",
            "explain_topic": "data_flow",
            "explain_depth": "beginner",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["mode"] == "explain"
    assert body["answer"].startswith("## Data flow")
    assert [(c["tool"], c["status"], c["error_code"]) for c in body["tool_calls"]] == [
        ("get_architecture", "ok", None),
        ("get_file_content", "ok", None),
        ("propose_fix", "denied", "read_only_project"),
    ]
    assert body["actions"] == []
    assert "shop/cart.py" in body["context"]["files_inspected"]

    # The topic and depth reach the system prompt as CodeWalk's own text.
    system = provider.requests[0].system
    assert "MODE: explain." in system
    assert "TOPIC: data_flow." in system
    assert "DEPTH: beginner." in system
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AgentAction)) == 0
        assert session.scalars(select(AgentRun.mode)).all() == ["explain"]


def test_explain_defaults_and_validation(make_client: Callable[..., Any]) -> None:
    client, provider, _ = make_client(answer("Overview."))
    project_id = make_project(client)["id"]

    response = client.post(
        "/api/v1/agent/run", json={"project_id": project_id, "message": "Explain", "mode": "explain"}
    )
    assert response.status_code == 200, response.text
    system = provider.requests[0].system
    assert "TOPIC: overview." in system
    assert "DEPTH: developer." in system

    for extra in (
        {"explain_topic": "database"},  # a topic needs mode "explain"
        {"mode": "explain", "explain_topic": "everything"},
        {"mode": "explain", "explain_depth": "expert"},
    ):
        bad = client.post("/api/v1/agent/run", json={"project_id": project_id, "message": "x", **extra})
        assert bad.status_code == 422, (extra, bad.text)
