"""Project intelligence with persistence: linked folders, rescans, stored projects."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import build_app
from tests.test_project_intelligence import write_project

LINKED_FILES = {
    "app/__init__.py": "",
    "app/main.py": "from app.util import helper\n\nhelper()\n",
    "app/util.py": "def helper():\n    return 1\n",
    "app/broken.py": "def broken(:\n",
    ".env": "SECRET=1\n",
}


def link(api: TestClient, workspace: Path, name: str = "linked") -> dict[str, Any]:
    write_project(workspace / name, LINKED_FILES)
    response = api.post("/api/v1/projects", json={"name": name, "root_path": name})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_workspace_listing(api: TestClient, workspace: Path) -> None:
    (workspace / "service-a").mkdir()
    (workspace / "node_modules").mkdir()
    assert api.get("/api/v1/projects/workspace").json() == {"enabled": True, "folders": ["service-a"]}


def test_linked_project_scan_and_rescan(api: TestClient, workspace: Path) -> None:
    project = link(api, workspace)
    assert project["read_only"] is True
    project_id = project["id"]

    assert api.get(f"/api/v1/projects/{project_id}/intelligence").status_code == 404  # not analyzed yet

    first = api.post(f"/api/v1/projects/{project_id}/analyze").json()
    assert first["sync"] == {"created": 4, "updated": 0, "deleted": 0, "unchanged": 0}
    assert {f["path"] for f in first["files"]} == {
        "app/__init__.py",
        "app/main.py",
        "app/util.py",
        "app/broken.py",
    }
    assert [e["path"] for e in first["errors"]] == ["app/broken.py"]  # reported, scan continued
    assert {
        "source": "app/main.py",
        "target": "app/util.py",
        "kind": "imports",
        "target_kind": "file",
        "line": 1,
    } in first["relationships"]
    assert first["analysis_id"]

    # Files now exist in the database, read-only through the file API.
    files = api.get(f"/api/v1/projects/{project_id}/files").json()["items"]
    assert files
    assert all(f["path"] != ".env" for f in files)
    blocked = api.post(f"/api/v1/projects/{project_id}/files", json={"path": "new.py"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "project_read_only"

    # Change the folder on disk: edit, add, delete.
    folder = workspace / "linked"
    (folder / "app/util.py").write_bytes(b"def helper():\n    return 2\n")
    (folder / "app/extra.py").write_bytes(b"VALUE = 1\n")
    (folder / "app/broken.py").unlink()
    second = api.post(f"/api/v1/projects/{project_id}/analyze").json()
    assert second["sync"] == {"created": 1, "updated": 1, "deleted": 1, "unchanged": 2}
    assert second["errors"] == []
    assert api.get(f"/api/v1/projects/{project_id}/files").json()["total"] == 4  # no duplicates

    latest = api.get(f"/api/v1/projects/{project_id}/intelligence").json()
    assert latest["analysis_id"] == second["analysis_id"]
    assert latest["statistics"]["total_files"] == 4

    history = api.get(
        f"/api/v1/projects/{project_id}/analyses", params={"analysis_type": "project_intelligence"}
    )
    assert history.json()["total"] == 2


def test_database_project_intelligence(api: TestClient) -> None:
    project_id = api.post("/api/v1/projects", json={"name": "stored"}).json()["id"]
    for path, content in (
        ("src/api.ts", "export const get = () => 1;\n"),
        ("src/app.ts", "import { get } from './api';\nget();\n"),
    ):
        api.post(f"/api/v1/projects/{project_id}/files", json={"path": path, "content": content})
    result = api.post(f"/api/v1/projects/{project_id}/analyze").json()
    assert result["sync"] is None  # nothing to scan: files live in the database
    assert result["directories"] == ["src"]
    app_file = next(f for f in result["files"] if f["path"] == "src/app.ts")
    assert app_file["imports"][0]["resolved_path"] == "src/api.ts"
    assert result["statistics"]["languages"] == [
        {"language": "typescript", "files": 2, "lines": 3, "bytes": 64}
    ]


def test_structure_cache_is_refreshed_after_edits(api: TestClient) -> None:
    project_id = api.post("/api/v1/projects", json={"name": "cache"}).json()["id"]
    file_id = api.post(
        f"/api/v1/projects/{project_id}/files", json={"path": "m.py", "content": "def a():\n    pass\n"}
    ).json()["file"]["id"]
    api.post(f"/api/v1/projects/{project_id}/analyze")
    api.patch(f"/api/v1/projects/{project_id}/files/{file_id}", json={"content": "def b():\n    pass\n"})
    latest = api.get(f"/api/v1/projects/{project_id}/intelligence").json()
    assert [s["name"] for s in latest["files"][0]["symbols"]] == ["b"]


def test_linking_rejects_traversal_and_missing_folders(api: TestClient) -> None:
    for root in ("../outside", "/etc", "C:\\Windows", "a/../../b"):
        assert (
            api.post("/api/v1/projects", json={"name": f"x{len(root)}", "root_path": root}).status_code == 422
        )
    missing = api.post("/api/v1/projects", json={"name": "missing", "root_path": "does-not-exist"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "folder_not_found"


def test_linking_requires_a_workspace(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client_factory(build_app(database_url=database_url))
    assert api.get("/api/v1/projects/workspace").json() == {"enabled": False, "folders": []}
    response = api.post("/api/v1/projects", json={"name": "x", "root_path": "anything"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "workspace_disabled"


def test_health_reports_connected_database(api: TestClient) -> None:
    body = api.get("/api/v1/health").json()
    database = next(check for check in body["checks"] if check["name"] == "database")
    assert database["status"] == "pass"
    assert body["status"] == "ok"
