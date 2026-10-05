"""AI change history and undo (GET /agent/actions, POST /agent/actions/{id}/undo)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.db.test_agent_api import FILES, answer, make_project, propose_run, run, tool
from tests.db.test_agent_api import make_client as make_client  # the fixture, used by name

API = "/api/v1"


def _content(client: TestClient, project: dict[str, Any], path: str) -> str:
    listing = client.get(f"{API}/projects/{project['id']}/files").json()["items"]
    file_id = next(f["id"] for f in listing if f["path"] == path)
    content: str = client.get(f"{API}/projects/{project['id']}/files/{file_id}").json()["content"]
    return content


def test_ai_changes_are_listed_with_what_why_and_status(make_client: Callable[..., Any]) -> None:
    client, project, body = propose_run(make_client)
    [action] = body["actions"]
    listed = client.get(f"{API}/agent/actions", params={"project_id": project["id"]}).json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert (item["id"], item["status"], item["file_path"]) == (action["id"], "pending", "shop/cart.py")
    assert item["summary"] == "Initialise total before the loop"
    assert item["explanation"] == "total is used before assignment."
    assert item["diff"]
    client.post(f"{API}/agent/actions/{action['id']}/approve")
    applied = client.get(
        f"{API}/agent/actions", params={"project_id": project["id"], "status": "applied"}
    ).json()
    assert [a["id"] for a in applied["items"]] == [action["id"]]


def test_undo_restores_the_content_before_the_ai_change(make_client: Callable[..., Any]) -> None:
    client, project, body = propose_run(make_client)
    [action] = body["actions"]
    assert client.post(f"{API}/agent/actions/{action['id']}/approve").status_code == 200
    assert _content(client, project, "shop/cart.py") != FILES["shop/cart.py"]

    undone = client.post(f"{API}/agent/actions/{action['id']}/undo")
    assert undone.status_code == 200, undone.text
    data = undone.json()
    assert data["deleted"] is False
    assert data["file"]["content"] == FILES["shop/cart.py"]
    assert data["action"]["result"]["undone"] is True
    assert _content(client, project, "shop/cart.py") == FILES["shop/cart.py"]
    # The AI version stays in the file's history (the undo is a new "restore" version).
    file_id = data["file"]["file_id"]
    versions = client.get(f"{API}/projects/{project['id']}/files/{file_id}/versions").json()
    items = versions["items"] if isinstance(versions, dict) else versions
    assert [v["source"] for v in sorted(items, key=lambda v: v["version"])] == ["create", "edit", "restore"]

    again = client.post(f"{API}/agent/actions/{action['id']}/undo")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "undo_not_possible"


def test_undo_refuses_when_the_file_changed_afterwards(make_client: Callable[..., Any]) -> None:
    client, project, body = propose_run(make_client)
    [action] = body["actions"]
    client.post(f"{API}/agent/actions/{action['id']}/approve")
    file_id = project["files"]["shop/cart.py"]
    client.patch(f"{API}/projects/{project['id']}/files/{file_id}", json={"content": "# my own edit\n"})
    refused = client.post(f"{API}/agent/actions/{action['id']}/undo")
    assert refused.status_code == 409
    assert "changed after this AI change" in refused.json()["error"]["message"]
    assert _content(client, project, "shop/cart.py") == "# my own edit\n"


def test_pending_or_rejected_changes_cannot_be_undone(make_client: Callable[..., Any]) -> None:
    client, _, body = propose_run(make_client)
    [action] = body["actions"]
    assert client.post(f"{API}/agent/actions/{action['id']}/undo").status_code == 409
    client.post(f"{API}/agent/actions/{action['id']}/reject")
    assert client.post(f"{API}/agent/actions/{action['id']}/undo").status_code == 409


def test_undo_of_a_created_file_removes_it(make_client: Callable[..., Any]) -> None:
    client, _, _ = make_client(
        tool(
            "propose_new_file",
            file_path="tests/test_cart.py",
            content="def test_total():\n    assert True\n",
            summary="Add a test",
            explanation="No tests exist for cart_total.",
        ),
        answer("Proposed a test file."),
    )
    project = make_project(client)
    [action] = run(client, project, "Add tests").json()["actions"]
    client.post(f"{API}/agent/actions/{action['id']}/approve")
    undone = client.post(f"{API}/agent/actions/{action['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["deleted"] is True
    listing = client.get(f"{API}/projects/{project['id']}/files").json()["items"]
    assert "tests/test_cart.py" not in {f["path"] for f in listing}


def test_deleting_a_file_keeps_its_ai_changes_in_the_history(make_client: Callable[..., Any]) -> None:
    client, project, body = propose_run(make_client)
    [action] = body["actions"]
    client.post(f"{API}/agent/actions/{action['id']}/approve")
    deleted = client.post(f"{API}/projects/{project['id']}/files/delete-path", json={"path": "shop/cart.py"})
    assert deleted.status_code == 200, deleted.text
    listed = client.get(f"{API}/agent/actions", params={"project_id": project["id"]}).json()["items"]
    assert [(a["id"], a["file_path"], a["status"]) for a in listed] == [
        (action["id"], "shop/cart.py", "applied")
    ]
    assert listed[0]["diff"]
    refused = client.post(f"{API}/agent/actions/{action['id']}/undo")
    assert refused.status_code == 409
    assert "no longer exists" in refused.json()["error"]["message"]


def test_another_user_sees_and_undoes_nothing(
    make_client: Callable[..., Any], client_factory: Callable[[FastAPI], TestClient]
) -> None:
    client, project, body = propose_run(make_client)
    [action] = body["actions"]
    client.post(f"{API}/agent/actions/{action['id']}/approve")
    other = client_factory(client.app)  # type: ignore[arg-type]
    from tests.db.conftest import register

    register(other, email="mallory@example.com", name="Mallory")
    assert other.get(f"{API}/agent/actions", params={"project_id": project["id"]}).status_code == 404
    assert other.post(f"{API}/agent/actions/{action['id']}/undo").status_code == 404
    assert _content(client, project, "shop/cart.py") != FILES["shop/cart.py"]  # still applied
