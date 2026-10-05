"""Importing an uploaded folder into Coding (POST /projects/{id}/editable-copy).

The upload stays unchanged as the original; the copy is a normal, editable Coding project whose files
start at version 1, are analyzed like any save, and can be edited, versioned and used by the agent.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

FILES = {
    "app/main.py": "from app.util import helper\n\nprint(helper())\n",
    "app/util.py": "def helper() -> int:\n    return undefined_name\n",
    "README.md": "# Demo\n",
}


def _upload(client: TestClient, name: str = "Shop upload") -> dict[str, Any]:
    project = client.post("/api/v1/projects", json={"name": name, "origin": "upload"})
    assert project.status_code == 201, project.text
    imported = client.post(
        f"/api/v1/projects/{project.json()['id']}/files/import",
        json={"files": [{"path": p, "content": c} for p, c in FILES.items()]},
    )
    assert imported.status_code == 200, imported.text
    body: dict[str, Any] = project.json()
    return body


def _files(client: TestClient, project_id: str) -> dict[str, dict[str, Any]]:
    listed = client.get(f"/api/v1/projects/{project_id}/files", params={"limit": 500}).json()["items"]
    return {f["path"]: f for f in listed}


def _content(client: TestClient, project_id: str, file_id: str) -> str:
    response = client.get(f"/api/v1/projects/{project_id}/files/{file_id}")
    assert response.status_code == 200, response.text
    content: str = response.json()["content"]
    return content


def test_an_upload_becomes_an_editable_coding_project(api: TestClient) -> None:
    upload = _upload(api)
    response = api.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={})
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["origin"] == "workspace"
    assert copy["name"] == "Shop upload (editable)"  # the upload keeps its name
    assert copy["stats"]["file_count"] == 3

    files = _files(api, copy["id"])
    assert sorted(files) == sorted(FILES)
    for path, content in FILES.items():
        assert _content(api, copy["id"], files[path]["id"]) == content
    # Each copied file starts its own history at version 1, analyzed like a normal save.
    versions = api.get(f"/api/v1/projects/{copy['id']}/files/{files['app/util.py']['id']}/versions").json()
    items = versions["items"] if isinstance(versions, dict) else versions
    assert [v["version"] for v in items] == [1]
    analyses = api.get(
        f"/api/v1/projects/{copy['id']}/analyses", params={"file_id": files["app/util.py"]["id"]}
    ).json()["items"]
    assert analyses
    assert analyses[0]["diagnostic_count"] >= 1  # the copied file was analyzed (undefined name)

    # The copy is editable; the original upload is unchanged.
    edited = api.patch(
        f"/api/v1/projects/{copy['id']}/files/{files['app/util.py']['id']}",
        json={"content": "def helper() -> int:\n    return 1\n"},
    )
    assert edited.status_code == 200, edited.text
    original = _files(api, upload["id"])
    assert _content(api, upload["id"], original["app/util.py"]["id"]) == FILES["app/util.py"]
    assert api.get(f"/api/v1/projects/{upload['id']}").json()["origin"] == "upload"

    # The copy appears with the Coding projects, the upload with the uploads.
    workspace = api.get("/api/v1/projects", params={"origin": "workspace"}).json()["items"]
    uploads = api.get("/api/v1/projects", params={"origin": "upload"}).json()["items"]
    assert copy["id"] in {p["id"] for p in workspace}
    assert upload["id"] in {p["id"] for p in uploads}


def test_names_stay_unique_and_can_be_chosen(api: TestClient) -> None:
    upload = _upload(api)
    first = api.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={}).json()
    second = api.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={}).json()
    named = api.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={"name": "Shop v2"}).json()
    assert [first["name"], second["name"], named["name"]] == [
        "Shop upload (editable)",
        "Shop upload (editable 2)",
        "Shop v2",
    ]


def test_only_uploads_are_imported(api: TestClient) -> None:
    project = api.post("/api/v1/projects", json={"name": "Workspace project"}).json()
    response = api.post(f"/api/v1/projects/{project['id']}/editable-copy", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_an_upload"


def test_another_users_upload_cannot_be_copied(api: TestClient, other_user: TestClient) -> None:
    upload = _upload(api)
    response = other_user.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={})
    assert response.status_code == 404
    assert other_user.get("/api/v1/projects").json()["total"] == 0  # nothing half-created


def test_invalid_names_are_refused(api: TestClient) -> None:
    upload = _upload(api)
    response = api.post(f"/api/v1/projects/{upload['id']}/editable-copy", json={"name": "a/b"})
    assert response.status_code == 422
