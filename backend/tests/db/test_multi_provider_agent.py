"""Module 19: the agent and its proposal workflow over every OpenAI-compatible provider.

The provider runs its real HTTP code against a mock transport that answers like the provider would;
the agent, tools, proposal, approval and file storage are the real application with PostgreSQL.
The agent uses one structured JSON answer per step (no native tool calling), so tool authorization
and the approval step are the server's own, whichever provider is selected.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.ai.providers.openai_compatible import (
    GEMINI,
    OLLAMA,
    OPENROUTER,
    CompatibleProfile,
    OpenAICompatibleProvider,
)
from app.services.ai.service import AIService
from tests.conftest import build_app, make_settings
from tests.db.conftest import register
from tests.db.test_agent_api import FILES, FIX_EDITS, answer, file_content, make_project, run, tool

SECRET = "provider-secret-key-0099"


def scripted(answers: list[dict[str, Any]], seen: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"headers": dict(request.headers), "body": body})
        content = json.dumps(answers.pop(0))
        return httpx.Response(
            200,
            json={
                "id": f"gen-{len(seen)}",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0001},
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("profile", [GEMINI, OPENROUTER, OLLAMA], ids=lambda p: p.name)
def test_agent_proposes_through_the_provider_and_nothing_changes_until_approved(
    profile: CompatibleProfile,
    database_url: str,
    workspace: Any,
    client_factory: Callable[[FastAPI], TestClient],
) -> None:
    seen: list[dict[str, Any]] = []
    answers = [
        tool("get_file_content", file_path="shop/cart.py"),
        tool(
            "propose_fix",
            file_path="shop/cart.py",
            summary="Initialise total before the loop",
            explanation="total is used before assignment.",
            edits=FIX_EDITS,
        ),
        answer("I proposed a fix for review."),
    ]
    api_key = None if profile is OLLAMA else SECRET
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        model="test-model",
        timeout_seconds=10,
        transport=scripted(answers, seen),
        profile=profile,
    )
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url), provider=provider
    )
    client = client_factory(app)
    register(client, email=f"provider-{profile.name}@example.com")
    project = make_project(client)

    response = run(client, project, "Fix the undefined total")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert [c["tool"] for c in body["tool_calls"]] == ["get_file_content", "propose_fix"]
    (action,) = body["actions"]
    assert action["status"] == "pending"
    assert file_content(client, project, "shop/cart.py") == FILES["shop/cart.py"]  # nothing written yet
    assert len(seen) == 3
    # The credential travels only in the header (none for Ollama); never in a prompt or a response.
    for request in seen:
        assert SECRET not in json.dumps(request["body"])
        assert ("authorization" in request["headers"]) is (api_key is not None)
    assert SECRET not in response.text

    approved = client.post(f"/api/v1/agent/actions/{action['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["action"]["status"] == "applied"
    assert "total = 0" in file_content(client, project, "shop/cart.py")


def test_provider_failure_ends_the_run_without_switching_provider(
    database_url: str, workspace: Any, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    calls: list[str] = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    provider = OpenAICompatibleProvider(
        api_key=SECRET, model="m", timeout_seconds=10, transport=httpx.MockTransport(down), profile=GEMINI
    )
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url), provider=provider
    )
    client = client_factory(app)
    register(client, email="provider-down@example.com")
    project = make_project(client)

    response = run(client, project)
    assert calls == ["generativelanguage.googleapis.com"]  # one call, one provider, no retry
    assert SECRET not in response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "ai_rate_limited"
