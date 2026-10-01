"""Activity history and file versions, recorded from real actions against PostgreSQL."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def events(api: TestClient, query: str = "") -> list[dict[str, Any]]:
    response = api.get(f"/api/v1/history{query}")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_new_user_has_no_history(api: TestClient) -> None:
    assert api.get("/api/v1/history").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_actions_are_recorded_in_order(api: TestClient) -> None:
    project = api.post("/api/v1/projects", json={"name": "Demo"}).json()
    pid = project["id"]
    saved = api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "import os\n"}).json()
    fid = saved["file"]["id"]
    api.patch(f"/api/v1/projects/{pid}/files/{fid}", json={"content": "x = (\n"})
    api.patch(f"/api/v1/projects/{pid}/files/{fid}", json={"path": "src/b.py"})
    api.post(f"/api/v1/projects/{pid}/files/{fid}/analyses")
    api.post(f"/api/v1/projects/{pid}/analyze")
    api.patch(f"/api/v1/projects/{pid}", json={"name": "Renamed", "description": "d"})

    newest_first = events(api)
    assert [e["event_type"] for e in newest_first] == [
        "project.updated",
        "project.analyzed",
        "file.analyzed",
        "file.updated",
        "file.updated",
        "file.created",
        "project.created",
    ]
    oldest_first = events(api, "?order=asc")
    assert [e["id"] for e in oldest_first] == [e["id"] for e in reversed(newest_first)]

    by_type = {e["event_type"]: e for e in reversed(newest_first)}  # last write wins: newest
    created = by_type["file.created"]
    assert created["file_path"] == "a.py"
    assert created["details"] == {"version": 1, "diagnostic_count": 1, "analysis_status": "completed"}
    assert created["analysis_id"] == saved["analysis"]["id"]

    edits = [e for e in newest_first if e["event_type"] == "file.updated"]
    assert edits[1]["details"]["version"] == 2  # content edit
    assert edits[1]["details"]["diagnostic_count"] >= 1  # the syntax error
    assert edits[0]["details"] == {"renamed_from": "a.py"}  # rename only: no new version or analysis
    assert edits[0]["file_path"] == "src/b.py"

    updated = by_type["project.updated"]
    assert updated["project_name"] == "Renamed"
    assert updated["details"] == {"changed": ["description", "name"], "renamed_from": "Demo"}
    analyzed = by_type["project.analyzed"]
    assert analyzed["details"]["statistics"]["files"] == 1
    assert analyzed["analysis_id"] is not None


def test_failed_and_no_op_actions_record_nothing(api: TestClient) -> None:
    pid = api.post("/api/v1/projects", json={"name": "Demo"}).json()["id"]
    assert api.post("/api/v1/projects", json={"name": "demo"}).status_code == 409
    assert api.patch(f"/api/v1/projects/{pid}", json={"name": "Demo"}).status_code == 200  # unchanged
    fid = api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "x = 1\n"}).json()[
        "file"
    ]["id"]
    assert api.patch(f"/api/v1/projects/{pid}/files/{fid}", json={"content": "x = 1\n"}).status_code == 200
    assert api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py"}).status_code == 409
    assert [e["event_type"] for e in events(api)] == ["file.created", "project.created"]


def test_filters_and_pagination(api: TestClient) -> None:
    first = api.post("/api/v1/projects", json={"name": "One"}).json()["id"]
    second = api.post("/api/v1/projects", json={"name": "Two"}).json()["id"]
    for index in range(3):
        api.post(f"/api/v1/projects/{second}/files", json={"path": f"f{index}.md", "content": "# hi\n"})

    assert {e["project_name"] for e in events(api, f"?project_id={first}")} == {"One"}
    assert len(events(api, f"?project_id={second}")) == 4
    files_only = events(api, "?event_type=file.created")
    assert len(files_only) == 3
    both = events(api, "?event_type=file.created&event_type=project.created")
    assert len(both) == 5

    page = api.get("/api/v1/history?limit=2&offset=1").json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["items"][0]["id"] == events(api)[1]["id"]

    assert api.get("/api/v1/history?event_type=made.up").status_code == 422
    assert api.get("/api/v1/history?limit=0").status_code == 422
    assert api.get("/api/v1/history?order=sideways").status_code == 422


def test_event_detail_links_back_to_current_locations(api: TestClient) -> None:
    pid = api.post("/api/v1/projects", json={"name": "Demo"}).json()["id"]
    saved = api.post(
        f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "import os\nx = (\n"}
    ).json()
    event_id = events(api)[0]["id"]
    api.patch(f"/api/v1/projects/{pid}/files/{saved['file']['id']}", json={"path": "moved.py"})

    detail = api.get(f"/api/v1/history/{event_id}").json()
    assert detail["file_path"] == "a.py"  # where it was
    assert detail["current_file_path"] == "moved.py"  # where it is now
    assert detail["project_exists"] is True
    assert detail["current_project_name"] == "Demo"
    analysis = detail["analysis"]
    assert analysis["id"] == saved["analysis"]["id"]
    assert analysis["diagnostic_count"] == sum(analysis["severity_counts"].values())
    assert analysis["severity_counts"].get("error", 0) >= 1


def test_history_survives_deletes(api: TestClient) -> None:
    pid = api.post("/api/v1/projects", json={"name": "Doomed"}).json()["id"]
    fid = api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "x = 1\n"}).json()[
        "file"
    ]["id"]
    assert api.delete(f"/api/v1/projects/{pid}/files/{fid}").status_code == 204
    file_deleted = events(api)[0]
    assert file_deleted["event_type"] == "file.deleted"
    assert file_deleted["file_path"] == "a.py"
    assert file_deleted["file_id"] is None

    assert api.delete(f"/api/v1/projects/{pid}").status_code == 204
    remaining = events(api)
    assert [e["event_type"] for e in remaining] == [
        "project.deleted",
        "file.deleted",
        "file.created",
        "project.created",
    ]
    assert all(e["project_id"] is None for e in remaining)  # links cleared by the database
    assert all(e["project_name"] == "Doomed" for e in remaining)
    detail = api.get(f"/api/v1/history/{remaining[2]['id']}").json()
    assert detail["project_exists"] is False
    assert detail["analysis"] is None
    assert detail["current_file_path"] is None


def test_file_versions_and_restore(api: TestClient) -> None:
    pid = api.post("/api/v1/projects", json={"name": "Versions"}).json()["id"]
    fid = api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "v1\n"}).json()["file"][
        "id"
    ]
    api.patch(f"/api/v1/projects/{pid}/files/{fid}", json={"content": "v2\n"})
    base = f"/api/v1/projects/{pid}/files/{fid}/versions"

    listing = api.get(base).json()
    assert listing["total"] == 2
    assert [v["version"] for v in listing["items"]] == [2, 1]
    assert "content" not in listing["items"][0]
    assert api.get(f"{base}/1").json()["content"] == "v1\n"
    assert api.get(f"{base}/9").status_code == 404
    assert api.get(f"{base}/0").status_code == 422

    restored = api.post(f"{base}/1/restore")
    assert restored.status_code == 200
    assert restored.json()["file"]["content"] == "v1\n"
    assert [v["source"] for v in api.get(base).json()["items"]] == ["restore", "edit", "create"]
    event = events(api)[0]
    assert event["event_type"] == "file.restored"
    assert event["details"]["restored_from"] == 1
    assert event["details"]["version"] == 3


def test_project_responses_include_real_statistics(api: TestClient) -> None:
    pid = api.post("/api/v1/projects", json={"name": "Stats", "description": "about"}).json()["id"]
    empty = api.get(f"/api/v1/projects/{pid}").json()
    assert empty["stats"] == {
        "file_count": 0,
        "total_bytes": 0,
        "total_lines": 0,
        "languages": [],
        "last_analyzed_at": None,
    }
    api.post(f"/api/v1/projects/{pid}/files", json={"path": "a.py", "content": "x = 1\n"})
    api.post(f"/api/v1/projects/{pid}/files", json={"path": "b.py", "content": "y = 2\n"})
    api.post(f"/api/v1/projects/{pid}/files", json={"path": "README.md", "content": "# R\n"})
    api.post(f"/api/v1/projects/{pid}/analyze")
    stats = api.get("/api/v1/projects").json()["items"][0]["stats"]
    assert stats["file_count"] == 3
    assert stats["total_lines"] == 3
    assert stats["languages"] == [{"language": "python", "files": 2}, {"language": "markdown", "files": 1}]
    assert stats["last_analyzed_at"] is not None


def test_project_names_cannot_contain_slashes(api: TestClient) -> None:
    for name in ("a/b", "a\\b"):
        assert api.post("/api/v1/projects", json={"name": name}).status_code == 422
