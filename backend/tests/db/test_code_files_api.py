"""Coding "+ New File": a code file from a file name only (POST /projects/{id}/files/code-file)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def _project(client: TestClient, **extra: Any) -> str:
    response = client.post("/api/v1/projects", json={"name": "Coding", **extra})
    assert response.status_code == 201, response.text
    project_id: str = response.json()["id"]
    return project_id


def _create(client: TestClient, project_id: str, name: str) -> Any:
    return client.post(f"/api/v1/projects/{project_id}/files/code-file", json={"name": name})


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("main.py", "python"),
        ("hello.java", "java"),
        ("app.js", "javascript"),
        ("index.ts", "typescript"),
        ("program.cpp", "cpp"),
        ("index.html", "html"),
    ],
)
def test_code_files_are_created_at_the_project_root(api: TestClient, name: str, language: str) -> None:
    project_id = _project(api)
    response = _create(api, project_id, name)
    assert response.status_code == 201, response.text
    file = response.json()["file"]
    assert (file["path"], file["name"], file["language"], file["content"]) == (name, name, language, "")


@pytest.mark.parametrize(
    "name",
    [
        "setup.exe",
        "lib.dll",
        "app.apk",
        "clip.mp4",
        "song.mp3",
        "a.zip",
        "a.7z",
        "logo.png",
        "photo.jpeg",
        "notes",
        ".py",
    ],
)
def test_non_code_files_are_rejected(api: TestClient, name: str) -> None:
    response = _create(api, _project(api), name)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert "Unsupported file type" in error["message"]


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "../../evil.py",
        "../../../secret.py",
        "C:\\Windows\\file.py",
        "/etc/passwd",
        "src/main.py",
        "folder\\file.py",
        ".",
        "..",
        "bad\x00name.py",
        "bad\x07name.py",
        "tab\tname.py",
        "what?.py",
        "C:file.py",
        "a" * 253 + ".py",
        ".env",
        ".env.local",
    ],
)
def test_unsafe_or_invalid_names_are_rejected(api: TestClient, name: str) -> None:
    project_id = _project(api)
    response = _create(api, project_id, name)
    assert response.status_code == 422, (name, response.text)
    assert response.json()["error"]["code"] in {"invalid_file_name", "validation_error"}
    assert api.get(f"/api/v1/projects/{project_id}/files").json()["total"] == 0


def test_an_existing_file_is_never_overwritten(api: TestClient) -> None:
    project_id = _project(api)
    created = _create(api, project_id, "main.py").json()["file"]
    api.patch(f"/api/v1/projects/{project_id}/files/{created['id']}", json={"content": "print('keep me')\n"})
    response = _create(api, project_id, "main.py")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_exists"
    detail = api.get(f"/api/v1/projects/{project_id}/files/{created['id']}").json()
    assert detail["content"] == "print('keep me')\n"


def test_only_the_owner_can_create_code_files(
    api: TestClient, other_user: TestClient, anonymous: TestClient
) -> None:
    project_id = _project(api)
    assert _create(other_user, project_id, "x.py").status_code == 404
    assert _create(anonymous, project_id, "x.py").status_code == 401
    assert api.get(f"/api/v1/projects/{project_id}/files").json()["total"] == 0


def test_uploaded_projects_are_not_edited_from_coding(api: TestClient) -> None:
    project_id = _project(api, origin="upload")
    response = _create(api, project_id, "main.py")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_read_only"
