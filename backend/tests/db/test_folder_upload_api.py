"""Uploading a local folder into a server project (POST /projects/{id}/files/import).

The browser sends the folder in batches; the server checks every file on its own and never
stores credentials, dependency folders, unsafe paths, or oversized content, and never overwrites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.conftest import build_app
from tests.db.conftest import register

FAKE_KEY = "AKIAFAKEFAKEFAKEFAKE"


def _project(client: TestClient, name: str = "Upload") -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _upload(client: TestClient, project_id: str, files: dict[str, str]) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={"files": [{"path": path, "content": content} for path, content in files.items()]},
    )


def test_uploaded_files_are_stored_and_unsafe_ones_are_reported(api: TestClient) -> None:
    project = _project(api)
    response = _upload(
        api,
        project["id"],
        {
            "app/main.py": "from app.util import helper\n\nprint(helper())\n",
            "app/util.py": "def helper() -> int:\n    return 1\n",
            "README.md": "# Demo\n",
            ".env": f"AWS_KEY={FAKE_KEY}\n",
            "config/.aws/credentials": f"aws_access_key_id = {FAKE_KEY}\n",
            "node_modules/lib/index.js": "module.exports = 1;\n",
            "../outside.py": "x = 1\n",
            "big.txt": "x" * (2 * 1024 * 1024 + 1),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(f["path"] for f in body["created"]) == ["README.md", "app/main.py", "app/util.py"]
    reasons = {s["path"]: s["reason"] for s in body["skipped"]}
    assert reasons == {
        ".env": "secret",
        "config/.aws/credentials": "secret",
        "node_modules/lib/index.js": "ignored",
        "../outside.py": "invalid_path",
        "big.txt": "too_large",
    }
    assert FAKE_KEY not in response.text

    files = api.get(f"/api/v1/projects/{project['id']}/files").json()
    assert sorted(f["path"] for f in files["items"]) == ["README.md", "app/main.py", "app/util.py"]
    main = next(f for f in files["items"] if f["path"] == "app/main.py")
    detail = api.get(f"/api/v1/projects/{project['id']}/files/{main['id']}").json()
    assert detail["content"].startswith("from app.util import helper")


def test_existing_files_are_never_overwritten_and_duplicates_are_skipped(api: TestClient) -> None:
    project = _project(api)
    assert _upload(api, project["id"], {"a.py": "a = 1\n"}).status_code == 200
    response = _upload(api, project["id"], {"a.py": "a = 2\n", "b.py": "b = 1\n"})
    body = response.json()
    assert [f["path"] for f in body["created"]] == ["b.py"]
    assert body["skipped"] == [
        {
            "path": "a.py",
            "reason": "exists",
            "message": "A file with this path already exists; it was not overwritten.",
        }
    ]
    files = api.get(f"/api/v1/projects/{project['id']}/files").json()["items"]
    a = next(f for f in files if f["path"] == "a.py")
    assert api.get(f"/api/v1/projects/{project['id']}/files/{a['id']}").json()["content"] == "a = 1\n"

    response = api.post(
        f"/api/v1/projects/{project['id']}/files/import",
        json={"files": [{"path": "c.py", "content": "1"}, {"path": "./c.py", "content": "2"}]},
    )
    assert [f["path"] for f in response.json()["created"]] == ["c.py"]
    assert [s["reason"] for s in response.json()["skipped"]] == ["duplicate"]


def test_uploaded_project_is_analyzed_and_searchable(api: TestClient) -> None:
    project = _project(api)
    _upload(
        api,
        project["id"],
        {
            "pkg/__init__.py": "",
            "pkg/pricing.py": "def order_total(x: int) -> int:\n    return x\n",
            "pkg/service.py": "from pkg.pricing import order_total\n\nTOTAL = order_total(3)\n",
        },
    )
    analysis = api.post(f"/api/v1/projects/{project['id']}/analyze")
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["statistics"]["total_files"] == 3
    search = api.post(f"/api/v1/projects/{project['id']}/search", json={"query": "order_total"})
    assert search.status_code == 200, search.text
    assert {r["file_path"] for r in search.json()["results"]} >= {"pkg/pricing.py", "pkg/service.py"}


def test_upload_requires_ownership_and_a_session(
    api: TestClient, other_user: TestClient, anonymous: TestClient
) -> None:
    project = _project(api)
    assert _upload(other_user, project["id"], {"x.py": "x = 1\n"}).status_code == 404
    assert _upload(anonymous, project["id"], {"x.py": "x = 1\n"}).status_code == 401
    assert api.get(f"/api/v1/projects/{project['id']}/files").json()["total"] == 0


def test_linked_projects_cannot_receive_uploads(api: TestClient, workspace: Path) -> None:
    (workspace / "linked").mkdir()
    project = api.post("/api/v1/projects", json={"name": "Linked", "root_path": "linked"}).json()
    response = _upload(api, project["id"], {"x.py": "x = 1\n"})
    assert response.status_code == 409


def test_batch_size_is_bounded(api: TestClient) -> None:
    project = _project(api)
    files = {f"f{i}.py": "" for i in range(101)}
    assert _upload(api, project["id"], files).status_code == 422


def test_project_file_limit_is_enforced(database_url: str, engine: Engine) -> None:
    app = build_app(database_url=database_url, scan_max_files=2)
    with TestClient(app) as client:
        register(client)
        project = _project(client)
        body = _upload(client, project["id"], {"a.py": "", "b.py": "", "c.py": ""}).json()
    assert [f["path"] for f in body["created"]] == ["a.py", "b.py"]
    assert [s["reason"] for s in body["skipped"]] == ["limit"]


# --- Request size: the browser batches stay under Vercel's 4.5 MB request body limit -------------

VERCEL_BODY_LIMIT = 4_500_000
MAX_SOURCE = 2 * 1024 * 1024


def _vercel_sized_client(database_url: str) -> TestClient:
    """The real app with the request body limit the API has behind Vercel."""
    app = build_app(
        database_url=database_url, max_request_body_bytes=VERCEL_BODY_LIMIT, max_source_bytes=MAX_SOURCE
    )
    return TestClient(app)


def test_a_batch_just_under_the_request_limit_is_stored(database_url: str, engine: Engine) -> None:
    files = {"big/a.py": "a" * 2_000_000 + "\n", "big/b.py": "b" * 2_000_000 + "\n", "small.py": "x = 1\n"}
    body = {"files": [{"path": p, "content": c} for p, c in files.items()]}
    assert VERCEL_BODY_LIMIT - 600_000 < len(json.dumps(body)) < VERCEL_BODY_LIMIT
    with _vercel_sized_client(database_url) as client:
        register(client)
        project = _project(client)
        response = _upload(client, project["id"], files)
        assert response.status_code == 200, response.text[:300]
        assert sorted(f["path"] for f in response.json()["created"]) == ["big/a.py", "big/b.py", "small.py"]
        stored = client.get(f"/api/v1/projects/{project['id']}/files").json()["items"]
        assert {f["path"]: f["size"] for f in stored}["big/a.py"] == 2_000_001


def test_a_batch_over_the_request_limit_is_refused_and_nothing_is_stored(
    database_url: str, engine: Engine
) -> None:
    files = {f"part{i}.py": str(i) * 1_600_000 for i in range(3)}  # each file is allowed; the request is not
    with _vercel_sized_client(database_url) as client:
        register(client)
        project = _project(client)
        response = _upload(client, project["id"], files)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"
        assert client.get(f"/api/v1/projects/{project['id']}/files").json()["total"] == 0


def test_malformed_uploads_are_rejected_without_storing_anything(api: TestClient) -> None:
    project = _project(api)
    url = f"/api/v1/projects/{project['id']}/files/import"
    json_headers = {"Content-Type": "application/json"}
    payload: dict[str, Any]
    assert api.post(url, content=b'{"files": [{"path": "a.py", "con', headers=json_headers).status_code == 422
    for payload in (
        {},
        {"files": []},
        {"files": "a.py"},
        {"files": [{"path": "a.py"}]},  # no content
        {"files": [{"path": "", "content": "x"}]},
        {"files": [{"path": "a.py", "content": 1}]},
        {"files": [{"path": "a.py", "content": "x", "mode": "755"}]},  # unknown field
    ):
        response = api.post(url, json=payload)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "validation_error"
    assert api.get(f"/api/v1/projects/{project['id']}/files").json()["total"] == 0


def test_uploads_stay_inside_their_project(api: TestClient, other_user: TestClient) -> None:
    first = _project(api, "First")
    second = _project(api, "Second")
    theirs = _project(other_user, "Theirs")
    assert _upload(api, first["id"], {"src/app.py": "first = 1\n"}).status_code == 200
    assert _upload(api, second["id"], {"src/app.py": "second = 2\n"}).status_code == 200
    assert _upload(other_user, theirs["id"], {"src/app.py": "theirs = 3\n"}).status_code == 200

    def content(client: TestClient, project_id: str) -> str:
        items = client.get(f"/api/v1/projects/{project_id}/files").json()["items"]
        assert [f["path"] for f in items] == ["src/app.py"]
        detail = client.get(f"/api/v1/projects/{project_id}/files/{items[0]['id']}").json()
        value: str = detail["content"]
        return value

    assert content(api, first["id"]) == "first = 1\n"
    assert content(api, second["id"]) == "second = 2\n"
    assert content(other_user, theirs["id"]) == "theirs = 3\n"
    assert _upload(api, theirs["id"], {"src/other.py": "x = 1\n"}).status_code == 404
    assert api.get(f"/api/v1/projects/{theirs['id']}/files").status_code == 404
