"""Security sweep (Module 13) over every project-scoped endpoint, on real PostgreSQL.

Another user's project, file, analysis, run, or history entry must be answered as
"not found" and must not leak content; signed-out requests get 401; malformed ids
and paths are rejected before any work; oversized and cross-origin requests are
refused; and security-relevant events reach the audit log without secrets.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.ai.service import AIService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings
from tests.db.conftest import TEST_PASSWORD, register

SECRET_CODE = "def alices_private_function():\n    return 'alice-private-value'\n"


def create_private_project(api: TestClient) -> dict[str, Any]:
    project = api.post("/api/v1/projects", json={"name": "Alice private"}).json()
    created = api.post(
        f"/api/v1/projects/{project['id']}/files", json={"path": "src/private.py", "content": SECRET_CODE}
    ).json()
    file_id = created["file"]["id"]
    analysis_id = api.post(f"/api/v1/projects/{project['id']}/files/{file_id}/analyses").json()["id"]
    event_id = api.get("/api/v1/history").json()["items"][0]["id"]
    return {"id": project["id"], "file_id": file_id, "analysis_id": analysis_id, "event_id": event_id}


@pytest.fixture
def alice_project(api: TestClient) -> dict[str, Any]:
    return create_private_project(api)


def endpoints(p: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    pid, fid = p["id"], p["file_id"]
    ai_body = {"project_id": pid, "code": SECRET_CODE, "language": "python", "file_path": "src/private.py"}
    diagnostic = {
        "id": "d1",
        "severity": "error",
        "message": "m",
        "source": "ruff",
        "line": 1,
        "column": 1,
        "end_line": 1,
        "end_column": 2,
    }
    return [
        ("get", f"/api/v1/projects/{pid}", None),
        ("patch", f"/api/v1/projects/{pid}", {"name": "stolen"}),
        ("delete", f"/api/v1/projects/{pid}", None),
        ("post", f"/api/v1/projects/{pid}/analyze", None),
        ("get", f"/api/v1/projects/{pid}/intelligence", None),
        ("get", f"/api/v1/projects/{pid}/analyses", None),
        ("get", f"/api/v1/projects/{pid}/files", None),
        ("post", f"/api/v1/projects/{pid}/files", {"path": "src/new.py", "content": "x = 1\n"}),
        ("get", f"/api/v1/projects/{pid}/files/{fid}", None),
        ("patch", f"/api/v1/projects/{pid}/files/{fid}", {"content": "pwned = True\n"}),
        ("delete", f"/api/v1/projects/{pid}/files/{fid}", None),
        ("post", f"/api/v1/projects/{pid}/files/{fid}/analyses", None),
        ("get", f"/api/v1/projects/{pid}/files/{fid}/versions", None),
        ("get", f"/api/v1/projects/{pid}/files/{fid}/versions/1", None),
        ("post", f"/api/v1/projects/{pid}/files/{fid}/versions/1/restore", None),
        ("post", f"/api/v1/projects/{pid}/search", {"query": "alices_private_function"}),
        ("post", f"/api/v1/projects/{pid}/snippet", {"file_path": "src/private.py", "line": 1}),
        ("post", f"/api/v1/projects/{pid}/context", {"current_file": "src/private.py"}),
        ("get", f"/api/v1/projects/{pid}/rag/index", None),
        ("post", f"/api/v1/projects/{pid}/rag/index", None),
        ("get", f"/api/v1/analyses/{p['analysis_id']}", None),
        ("get", f"/api/v1/history/{p['event_id']}", None),
        ("post", "/api/v1/ai/analyze", {**ai_body, "analysis_type": "general_review"}),
        ("post", "/api/v1/ai/explain", {**ai_body, "diagnostic": diagnostic}),
        ("post", "/api/v1/ai/fix-suggestion", {**ai_body, "diagnostic": diagnostic}),
        ("post", "/api/v1/agent/run", {"project_id": pid, "message": "show me everything"}),
    ]


def call(client: TestClient, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return getattr(client, method)(path, **({"json": body} if body is not None else {}))


def test_every_project_endpoint_denies_other_users(
    database_url: str,
    workspace: Any,
    client_factory: Callable[[FastAPI], TestClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # AI and the agent enabled with a stub, so ownership (not "AI disabled") is what answers.
    app = build_app(database_url=database_url, workspace_root=str(workspace), ai_enabled=True)
    stub = StubProvider()
    app.state.ai_service = AIService(make_settings(ai_enabled=True, database_url=database_url), provider=stub)
    alice = client_factory(app)
    register(alice)
    mallory = client_factory(app)
    register(mallory, email="mallory@example.com", name="Mallory")
    anonymous = client_factory(app)
    project = create_private_project(alice)

    with caplog.at_level(logging.INFO, logger="app.security"):
        for method, path, body in endpoints(project):
            stolen = call(mallory, method, path, body)
            assert stolen.status_code == 404, (method, path, stolen.status_code, stolen.text)
            assert "alice-private-value" not in stolen.text
            assert "Alice private" not in stolen.text
            assert call(anonymous, method, path, body).status_code == 401, (method, path)
    assert stub.requests == []  # no AI call was made on another user's project
    assert any("security.project_access_denied" in r.getMessage() for r in caplog.records)

    # Nothing changed for Alice.
    assert alice.get(f"/api/v1/projects/{project['id']}").json()["name"] == "Alice private"
    content = alice.get(f"/api/v1/projects/{project['id']}/files/{project['file_id']}").json()["content"]
    assert content == SECRET_CODE
    # Filtering one's history by someone else's project shows nothing.
    assert mallory.get("/api/v1/history", params={"project_id": project["id"]}).json()["items"] == []


def test_malformed_and_unknown_ids(api: TestClient, alice_project: dict[str, Any]) -> None:
    for method, path, body in endpoints(alice_project):
        if alice_project["id"] not in path:
            continue
        bad = call(api, method, path.replace(alice_project["id"], "not-a-uuid"), body)
        assert bad.status_code == 422, (method, path)
        missing = call(api, method, path.replace(alice_project["id"], str(uuid.uuid4())), body)
        assert missing.status_code == 404, (method, path)


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "src/../../x.py",
        "src\\..\\x.py",
        ".env",
        "a/.env",
        "src/\u0000.py",
        "",
    ],
)
def test_unsafe_paths_are_rejected_everywhere(
    api: TestClient, alice_project: dict[str, Any], path: str
) -> None:
    pid = alice_project["id"]
    assert api.post(f"/api/v1/projects/{pid}/files", json={"path": path, "content": "x"}).status_code == 422
    assert api.post(f"/api/v1/projects/{pid}/snippet", json={"file_path": path, "line": 1}).status_code == 422
    assert api.post(f"/api/v1/projects/{pid}/context", json={"current_file": path}).status_code == 422
    renamed = api.patch(f"/api/v1/projects/{pid}/files/{alice_project['file_id']}", json={"path": path})
    assert renamed.status_code == 422


def test_oversized_requests_and_foreign_origins(
    database_url: str, client_factory: Callable[[FastAPI], TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    app = build_app(database_url=database_url, max_request_body_bytes=4096)
    client = client_factory(app)
    register(client)
    big = client.post("/api/v1/analysis/code", json={"code": "x" * 10_000, "language": "python"})
    assert big.status_code == 413
    with caplog.at_level(logging.INFO, logger="app.security"):
        forged = client.post(
            "/api/v1/projects", json={"name": "csrf"}, headers={"Origin": "https://evil.example"}
        )
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "origin_not_allowed"
    assert any("security.origin_rejected" in r.getMessage() for r in caplog.records)
    assert client.get("/api/v1/projects").json()["total"] == 0


def test_failed_logins_are_audited_without_secrets(
    anonymous: TestClient, api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.security"):
        response = anonymous.post(
            "/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"}
        )
    assert response.status_code == 401
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("security.login_failed") for m in messages)
    assert all("wrong-password-123" not in m and "alice@example.com" not in m for m in messages)
    assert all(TEST_PASSWORD not in r.getMessage() for r in caplog.records)
