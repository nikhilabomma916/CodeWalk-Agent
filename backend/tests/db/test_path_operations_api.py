"""Explorer operations on server projects: rename/move a file or a folder, delete a file or a folder.

Each operation is one transaction: either every file of a folder moves (or is deleted), or none.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

FILES = {
    "src/app/main.py": "from app.db import connect\n",
    "src/app/db.py": "def connect():\n    return 1\n",
    "src/app/util/helpers.py": "X = 1\n",
    "README.md": "# Demo\n",
}


def _project(client: TestClient) -> str:
    project = client.post("/api/v1/projects", json={"name": "Explorer"}).json()
    for path, content in FILES.items():
        created = client.post(
            f"/api/v1/projects/{project['id']}/files", json={"path": path, "content": content}
        )
        assert created.status_code == 201, created.text
    project_id: str = project["id"]
    return project_id


def _paths(client: TestClient, project_id: str) -> list[str]:
    return [f["path"] for f in client.get(f"/api/v1/projects/{project_id}/files").json()["items"]]


def _rename(client: TestClient, project_id: str, from_path: str, to_path: str) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/files/rename-path", json={"from_path": from_path, "to_path": to_path}
    )


def test_rename_a_file_keeps_its_content_and_history(api: TestClient) -> None:
    pid = _project(api)
    response = _rename(api, pid, "src/app/db.py", "src/app/database.py")
    assert response.status_code == 200, response.text
    assert response.json() == {"paths": ["src/app/database.py"]}
    files = {f["path"]: f for f in api.get(f"/api/v1/projects/{pid}/files").json()["items"]}
    assert "src/app/db.py" not in files
    moved = files["src/app/database.py"]
    detail = api.get(f"/api/v1/projects/{pid}/files/{moved['id']}").json()
    assert detail["content"] == FILES["src/app/db.py"]
    versions = api.get(f"/api/v1/projects/{pid}/files/{moved['id']}/versions").json()
    items = versions["items"] if isinstance(versions, dict) else versions
    assert len(items) >= 1  # the file's history survives the rename


def test_move_a_file_into_another_folder(api: TestClient) -> None:
    pid = _project(api)
    assert _rename(api, pid, "README.md", "docs/README.md").status_code == 200
    assert "docs/README.md" in _paths(api, pid)
    assert "README.md" not in _paths(api, pid)


def test_rename_a_folder_moves_everything_in_it(api: TestClient) -> None:
    pid = _project(api)
    response = _rename(api, pid, "src/app", "src/core")
    assert response.status_code == 200, response.text
    assert sorted(response.json()["paths"]) == [
        "src/core/db.py",
        "src/core/main.py",
        "src/core/util/helpers.py",
    ]
    assert sorted(_paths(api, pid)) == sorted(
        ["README.md", "src/core/db.py", "src/core/main.py", "src/core/util/helpers.py"]
    )


def test_move_a_folder_up_into_an_ancestor(api: TestClient) -> None:
    pid = _project(api)
    response = _rename(api, pid, "src/app/util", "src/util")
    assert response.status_code == 200, response.text
    assert "src/util/helpers.py" in _paths(api, pid)


def test_conflicts_and_invalid_moves_change_nothing(api: TestClient) -> None:
    pid = _project(api)
    before = sorted(_paths(api, pid))
    taken = _rename(api, pid, "src/app/db.py", "src/app/main.py")
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "file_exists"
    into_itself = _rename(api, pid, "src/app", "src/app/inner")
    assert into_itself.status_code == 422
    assert into_itself.json()["error"]["code"] == "invalid_move"
    missing = _rename(api, pid, "nope", "other")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "path_not_found"
    unsafe = _rename(api, pid, "README.md", "../outside.md")
    assert unsafe.status_code == 422
    # A folder move that would overwrite an existing file moves nothing at all.
    api.post(f"/api/v1/projects/{pid}/files", json={"path": "lib/db.py", "content": "y = 2\n"})
    partial = _rename(api, pid, "src/app", "lib")
    assert partial.status_code == 409
    assert sorted(_paths(api, pid)) == sorted([*before, "lib/db.py"])


def test_delete_a_file_or_a_folder(api: TestClient) -> None:
    pid = _project(api)
    one = api.post(f"/api/v1/projects/{pid}/files/delete-path", json={"path": "README.md"})
    assert one.status_code == 200, one.text
    assert one.json() == {"paths": ["README.md"]}
    folder = api.post(f"/api/v1/projects/{pid}/files/delete-path", json={"path": "src/app/util"})
    assert folder.json() == {"paths": ["src/app/util/helpers.py"]}
    assert sorted(_paths(api, pid)) == ["src/app/db.py", "src/app/main.py"]
    # Deletions are in the project history.
    events = api.get("/api/v1/history", params={"project_id": pid}).json()["items"]
    assert sum(1 for e in events if e["event_type"] == "file.deleted") == 2


def test_another_user_cannot_rename_or_delete(api: TestClient, other_user: TestClient) -> None:
    pid = _project(api)
    assert _rename(other_user, pid, "README.md", "x.md").status_code == 404
    assert (
        other_user.post(f"/api/v1/projects/{pid}/files/delete-path", json={"path": "src"}).status_code == 404
    )
    assert sorted(_paths(api, pid)) == sorted(FILES)
