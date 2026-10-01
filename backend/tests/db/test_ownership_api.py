"""Project ownership: no user can read or change another user's data (IDOR), and
nothing is reachable without signing in. Enforced by the API, not the frontend."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def alice_data(api: TestClient) -> dict[str, Any]:
    """Alice's project with a saved file, an analysis, a version, and history."""
    project = api.post("/api/v1/projects", json={"name": "Private", "description": "secret plans"}).json()
    saved = api.post(
        f"/api/v1/projects/{project['id']}/files", json={"path": "main.py", "content": "import os\n"}
    ).json()
    api.post(f"/api/v1/projects/{project['id']}/analyze")
    event = api.get("/api/v1/history").json()["items"][0]
    return {
        "project": project["id"],
        "file": saved["file"]["id"],
        "analysis": saved["analysis"]["id"],
        "event": event["id"],
    }


def requests_for(ids: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    p, f = ids["project"], ids["file"]
    base = f"/api/v1/projects/{p}"
    return [
        ("GET", base, None),
        ("PATCH", base, {"name": "Hijacked"}),
        ("DELETE", base, None),
        ("POST", f"{base}/analyze", None),
        ("GET", f"{base}/intelligence", None),
        ("GET", f"{base}/analyses", None),
        ("GET", f"{base}/files", None),
        ("POST", f"{base}/files", {"path": "evil.py", "content": "x"}),
        ("GET", f"{base}/files/{f}", None),
        ("PATCH", f"{base}/files/{f}", {"content": "overwritten"}),
        ("DELETE", f"{base}/files/{f}", None),
        ("POST", f"{base}/files/{f}/analyses", None),
        ("GET", f"{base}/files/{f}/versions", None),
        ("GET", f"{base}/files/{f}/versions/1", None),
        ("POST", f"{base}/files/{f}/versions/1/restore", None),
        ("GET", f"/api/v1/analyses/{ids['analysis']}", None),
        ("GET", f"/api/v1/history/{ids['event']}", None),
    ]


def test_other_users_cannot_reach_a_project(api: TestClient, other_user: TestClient) -> None:
    ids = alice_data(api)
    for method, url, body in requests_for(ids):
        response = other_user.request(method, url, json=body)
        # 404, not 403: another user's project is indistinguishable from a missing one.
        assert response.status_code == 404, (method, url, response.text)
        assert "Private" not in response.text
        assert "secret plans" not in response.text

    assert other_user.get("/api/v1/projects").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert other_user.get("/api/v1/history").json()["total"] == 0
    assert other_user.get(f"/api/v1/history?project_id={ids['project']}").json()["total"] == 0

    # Alice's data is untouched by every attempt.
    project = api.get(f"/api/v1/projects/{ids['project']}").json()
    assert project["name"] == "Private"
    content = api.get(f"/api/v1/projects/{ids['project']}/files/{ids['file']}").json()["content"]
    assert content == "import os\n"
    assert api.get(f"/api/v1/projects/{ids['project']}/files").json()["total"] == 1


def test_signed_out_requests_are_rejected(api: TestClient, anonymous: TestClient) -> None:
    ids = alice_data(api)
    urls = [
        *requests_for(ids),
        ("GET", "/api/v1/projects", None),
        ("POST", "/api/v1/projects", {"name": "X"}),
    ]
    urls += [("GET", "/api/v1/history", None), ("GET", "/api/v1/projects/workspace", None)]
    for method, url, body in urls:
        response = anonymous.request(method, url, json=body)
        assert response.status_code == 401, (method, url)
        assert response.json()["error"]["code"] == "not_authenticated"


def test_each_user_sees_only_their_projects(api: TestClient, other_user: TestClient) -> None:
    api.post("/api/v1/projects", json={"name": "Shared name"})
    # Names are unique per user, so another user may reuse one.
    assert other_user.post("/api/v1/projects", json={"name": "Shared name"}).status_code == 201
    assert [p["name"] for p in api.get("/api/v1/projects").json()["items"]] == ["Shared name"]
    assert api.get("/api/v1/projects").json()["total"] == 1
    assert other_user.get("/api/v1/projects").json()["total"] == 1


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_ids_are_not_found_or_invalid(api: TestClient, bad_id: str) -> None:
    status = api.get(f"/api/v1/history/{bad_id}").status_code
    assert status in {404, 422}
