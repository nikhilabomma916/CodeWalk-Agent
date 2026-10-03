"""Live smoke test of the agent against the real AI provider and PostgreSQL.

Runs only when an AI credential is present in the server environment; skipped
otherwise, so the normal suite never depends on (or pays for) a provider.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import build_app
from tests.db.conftest import register

CREDENTIAL = os.environ.get("CODEWALK_AI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

pytestmark = pytest.mark.skipif(
    not CREDENTIAL, reason="Live agent test not executed: no AI credential is configured"
)


def test_live_agent_answers_from_project_tools(
    database_url: str, workspace: Any, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app = build_app(
        database_url=database_url,
        workspace_root=str(workspace),
        ai_enabled=True,
        ai_api_key=CREDENTIAL,
        ai_effort="low",
        agent_max_steps=5,
    )
    client = client_factory(app)
    register(client)
    project = client.post("/api/v1/projects", json={"name": "Live"}).json()
    client.post(
        f"/api/v1/projects/{project['id']}/files",
        json={
            "path": "shop/cart.py",
            "content": "def cart_total(items):\n    return sum(i.price for i in items)\n",
        },
    )
    response = client.post(
        "/api/v1/agent/run",
        json={"project_id": project["id"], "message": "Where is cart_total defined and what does it return?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"completed", "limit_reached"}, body.get("error")
    assert body["tool_calls"], "the agent should use project tools"
    assert body["actions"] == []  # nothing proposed for a question
    if body["status"] == "completed":
        assert "cart" in body["answer"].lower()
