"""Focused context: the agent fetches only what a question needs, and project history is available
on request through a read-only, owner-scoped tool (get_project_activity)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.db.test_agent_api import FILES, answer, make_client, make_project, tool

__all__ = ["make_client"]  # the fixture is used by name below

API = "/api/v1"


def _ask(client: TestClient, project: dict[str, Any], message: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"{API}/agent/run", json={"project_id": project["id"], "message": message, **extra}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_project_history_comes_only_from_this_users_project(
    make_client: Callable[..., Any],
) -> None:
    client, stub, _ = make_client(
        tool("get_project_activity", limit=20),
        answer("You created the shop module files."),
    )
    project = make_project(client)
    other = client.post(f"{API}/projects", json={"name": "Elsewhere"}).json()
    client.post(
        f"{API}/projects/{other['id']}/files", json={"path": "plans/private_roadmap.py", "content": ""}
    )

    body = _ask(client, project, "What have we done in this project?")
    assert [(c["tool"], c["status"]) for c in body["tool_calls"]] == [("get_project_activity", "ok")]
    seen = stub.requests[1].user  # the tool result is data in the next model turn
    assert "file.created" in seen
    assert all(path in seen for path in FILES)
    assert "private_roadmap" not in seen  # another project of the same user


def test_project_history_can_be_narrowed(make_client: Callable[..., Any]) -> None:
    client, stub, _ = make_client(
        tool("get_project_activity", kind="agent", since_days=1),
        answer("No agent activity yet."),
    )
    project = make_project(client)
    _ask(client, project, "What did the agent change recently?")
    result = stub.requests[1].user
    assert "file.created" not in result
    assert '"events":[]' in result.replace(" ", "")


def test_a_general_question_sends_no_project_files(make_client: Callable[..., Any]) -> None:
    client, stub, _ = make_client(answer("A list comprehension builds a list from an iterable."))
    project = make_project(client)
    body = _ask(client, project, "What is a Python list comprehension?")
    assert body["tool_calls"] == []
    request = stub.requests[0]
    assert "Answer the developer's actual question, and only that" in request.system
    assert "get_project_activity" in request.system
    for content in FILES.values():
        if content.strip():
            assert content.strip().splitlines()[0] not in request.user  # no file contents were sent


def test_the_open_file_and_selection_are_the_first_context(make_client: Callable[..., Any]) -> None:
    client, stub, _ = make_client(answer("total is used before assignment."))
    project = make_project(client)
    code = FILES["shop/cart.py"]
    _ask(
        client,
        project,
        "Explain this selected function.",
        file_path="shop/cart.py",
        code=code,
        selection={"start_line": 1, "start_column": 1, "end_line": 2, "end_column": 1},
    )
    user = stub.requests[0].user
    assert 'open_file="shop/cart.py"' in user
    assert "from shop.pricing import price_of" in user  # the selected lines
