"""Project and file APIs end-to-end against real PostgreSQL."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import build_app


def create_project(api: TestClient, name: str = "Demo", **extra: Any) -> dict[str, Any]:
    response = api.post("/api/v1/projects", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def create_file(api: TestClient, project_id: str, path: str, content: str = "") -> dict[str, Any]:
    response = api.post(f"/api/v1/projects/{project_id}/files", json={"path": path, "content": content})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Projects ----------------------------------------------------------------------


def test_project_crud(api: TestClient) -> None:
    project = create_project(api, "  Alpha  ", description="first")
    assert project["name"] == "Alpha"  # trimmed
    assert project["read_only"] is False
    project_id = project["id"]

    assert api.get(f"/api/v1/projects/{project_id}").json()["description"] == "first"

    listing = api.get("/api/v1/projects").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == project_id

    renamed = api.patch(f"/api/v1/projects/{project_id}", json={"name": "Beta"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Beta"

    assert api.delete(f"/api/v1/projects/{project_id}").status_code == 204
    missing = api.get(f"/api/v1/projects/{project_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"


def test_duplicate_project_names_conflict(api: TestClient) -> None:
    create_project(api, "Demo")
    response = api.post("/api/v1/projects", json={"name": "DEMO"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_exists"

    other = create_project(api, "Other")
    rename = api.patch(f"/api/v1/projects/{other['id']}", json={"name": "demo"})
    assert rename.status_code == 409


def test_invalid_project_payloads(api: TestClient) -> None:
    for payload in (
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "a\x00b"},
        {},
        {"name": 5},
        {"name": "ok", "unexpected": 1},
    ):
        assert api.post("/api/v1/projects", json=payload).status_code == 422, payload


def test_invalid_and_unknown_ids(api: TestClient) -> None:
    assert api.get("/api/v1/projects/not-a-uuid").status_code == 422
    assert api.get(f"/api/v1/projects/{uuid.uuid4()}").status_code == 404
    assert api.delete(f"/api/v1/projects/{uuid.uuid4()}").status_code == 404


def test_project_pagination(api: TestClient) -> None:
    for index in range(3):
        create_project(api, f"P{index}")
    page = api.get("/api/v1/projects", params={"limit": 2, "offset": 0}).json()
    assert (page["total"], len(page["items"]), page["limit"]) == (3, 2, 2)
    assert len(api.get("/api/v1/projects", params={"limit": 2, "offset": 2}).json()["items"]) == 1
    assert api.get("/api/v1/projects", params={"limit": 0}).status_code == 422


# --- Files ---------------------------------------------------------------------------


def test_file_crud_with_recorded_analysis(api: TestClient) -> None:
    project_id = create_project(api)["id"]
    saved = create_file(api, project_id, "src/app.py", "import os\n")
    file = saved["file"]
    assert (file["path"], file["name"], file["language"], file["line_count"]) == (
        "src/app.py",
        "app.py",
        "python",
        1,
    )
    assert saved["analysis"]["diagnostic_count"] == 1  # unused import, recorded on save

    listing = api.get(f"/api/v1/projects/{project_id}/files").json()
    assert listing["total"] == 1
    assert "content" not in listing["items"][0]  # listings never carry content

    detail = api.get(f"/api/v1/projects/{project_id}/files/{file['id']}").json()
    assert detail["content"] == "import os\n"

    fixed = api.patch(f"/api/v1/projects/{project_id}/files/{file['id']}", json={"content": "print('ok')\n"})
    assert fixed.status_code == 200
    assert fixed.json()["analysis"]["diagnostic_count"] == 0
    assert fixed.json()["file"]["content_hash"] != file["content_hash"]

    renamed = api.patch(f"/api/v1/projects/{project_id}/files/{file['id']}", json={"path": "src/main.py"})
    assert renamed.json()["file"]["path"] == "src/main.py"
    assert renamed.json()["analysis"] is None  # rename only: nothing re-analyzed

    assert api.delete(f"/api/v1/projects/{project_id}/files/{file['id']}").status_code == 204
    assert api.get(f"/api/v1/projects/{project_id}/files/{file['id']}").status_code == 404


def test_analysis_history_and_diagnostics(api: TestClient) -> None:
    project_id = create_project(api)["id"]
    file = create_file(api, project_id, "bad.py", "def broken(:\n")["file"]

    history = api.get(f"/api/v1/projects/{project_id}/analyses", params={"file_id": file["id"]}).json()
    assert history["total"] == 1
    analysis_id = history["items"][0]["id"]

    detail = api.get(f"/api/v1/analyses/{analysis_id}").json()
    assert detail["status"] == "completed"
    assert detail["language"] == "python"
    [diagnostic] = detail["diagnostics"]
    assert (diagnostic["severity"], diagnostic["category"], diagnostic["line"]) == ("error", "syntax", 1)

    manual = api.post(f"/api/v1/projects/{project_id}/files/{file['id']}/analyses")
    assert manual.status_code == 201
    assert len(manual.json()["diagnostics"]) == 1
    assert api.get(f"/api/v1/projects/{project_id}/analyses").json()["total"] == 2
    assert api.get(f"/api/v1/analyses/{uuid.uuid4()}").status_code == 404


def test_history_is_capped_per_file(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client_factory(
        build_app(database_url=database_url, workspace_root=str(workspace), analysis_history_per_file=2)
    )
    project_id = create_project(api)["id"]
    file_id = create_file(api, project_id, "a.py", "x = 0\n")["file"]["id"]
    for value in range(1, 5):
        api.patch(f"/api/v1/projects/{project_id}/files/{file_id}", json={"content": f"x = {value}\n"})
    assert api.get(f"/api/v1/projects/{project_id}/analyses").json()["total"] == 2


def test_file_conflicts_and_validation(api: TestClient) -> None:
    project_id = create_project(api)["id"]
    first = create_file(api, project_id, "a.py")["file"]
    create_file(api, project_id, "b.py")

    duplicate = api.post(f"/api/v1/projects/{project_id}/files", json={"path": "a.py"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "file_exists"
    rename_clash = api.patch(f"/api/v1/projects/{project_id}/files/{first['id']}", json={"path": "b.py"})
    assert rename_clash.status_code == 409

    for bad_path in (
        "../escape.py",
        "/abs.py",
        "C:\\x.py",
        "a/../../b.py",
        ".env",
        "config/.env.local",
        "a\x00.py",
    ):
        response = api.post(f"/api/v1/projects/{project_id}/files", json={"path": bad_path})
        assert response.status_code == 422, bad_path
    assert api.post(f"/api/v1/projects/{uuid.uuid4()}/files", json={"path": "x.py"}).status_code == 404


def test_oversized_file_content(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client_factory(
        build_app(database_url=database_url, workspace_root=str(workspace), max_source_bytes=100)
    )
    project_id = create_project(api)["id"]
    response = api.post(f"/api/v1/projects/{project_id}/files", json={"path": "big.py", "content": "x" * 101})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "content_too_large"
