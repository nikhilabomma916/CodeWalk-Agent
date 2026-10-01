"""Live integration checks against running backend and frontend servers.

Start both services first (``npm run dev``), then run ``npm run test:integration``.
Override targets with CODEWALK_STACK_API_URL / CODEWALK_STACK_FRONTEND_URL.
Unlike the unit suites, these tests fail (rather than skip) when a service is down,
because they are only run deliberately against a live stack.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = os.environ.get("CODEWALK_STACK_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
FRONTEND_URL = os.environ.get("CODEWALK_STACK_FRONTEND_URL", "http://localhost:3000").rstrip("/")
FRONTEND_ORIGIN = os.environ.get("CODEWALK_STACK_FRONTEND_ORIGIN", "http://localhost:3000")


@pytest.fixture(scope="module")
def http() -> httpx.Client:
    with httpx.Client(timeout=10.0) as client:
        yield client


def test_backend_health_is_real_and_structured(http: httpx.Client) -> None:
    response = http.get(f"{API_URL}/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert {"service", "version", "environment", "timestamp", "uptime_seconds", "checks"} <= body.keys()
    assert response.headers["X-Request-ID"]


def test_backend_allows_frontend_origin(http: httpx.Client) -> None:
    preflight = http.options(
        f"{API_URL}/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_backend_rejects_foreign_origin(http: httpx.Client) -> None:
    response = http.get(f"{API_URL}/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_backend_error_contract(http: httpx.Client) -> None:
    missing = http.get(f"{API_URL}/definitely-not-a-route")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    # Larger than the default CODEWALK_MAX_REQUEST_BODY_BYTES (6 MiB).
    too_large = http.post(f"{API_URL}/health", content=b"x" * (7 * 1024 * 1024))
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "payload_too_large"


def test_frontend_serves_workspace(http: httpx.Client) -> None:
    page = http.get(FRONTEND_URL)
    assert page.status_code == 200
    assert "<title>CodeWalk Agent</title>" in page.text


def test_frontend_serves_self_hosted_monaco(http: httpx.Client) -> None:
    loader = http.get(f"{FRONTEND_URL}/monaco/vs/loader.js")
    assert loader.status_code == 200
    assert len(loader.content) > 1000


# --- Accounts, projects, history, and ownership against the running stack ------------

LIVE_PASSWORD = "live-check-Pass-7"


def _signed_in_client(name: str) -> tuple[httpx.Client, str]:
    import uuid

    email = f"live-{name}-{uuid.uuid4().hex[:10]}@example.com"
    client = httpx.Client(timeout=30.0, headers={"Origin": FRONTEND_ORIGIN})
    response = client.post(
        f"{API_URL}/auth/register", json={"email": email, "name": name.title(), "password": LIVE_PASSWORD}
    )
    assert response.status_code == 201, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return client, email


def test_full_account_project_history_flow() -> None:
    owner, email = _signed_in_client("owner")
    intruder, _ = _signed_in_client("intruder")
    try:
        # Log out and back in with the same credentials.
        assert owner.post(f"{API_URL}/auth/logout").status_code == 204
        assert owner.get(f"{API_URL}/auth/me").status_code == 401
        login = owner.post(f"{API_URL}/auth/login", json={"email": email, "password": LIVE_PASSWORD})
        assert login.status_code == 200, login.text

        project = owner.post(f"{API_URL}/projects", json={"name": "Live check", "description": "integration"})
        assert project.status_code == 201, project.text
        pid = project.json()["id"]
        saved = owner.post(
            f"{API_URL}/projects/{pid}/files", json={"path": "app.py", "content": "def f(:\n    pass\n"}
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["analysis"]["diagnostic_count"] >= 1  # the syntax error was found
        fid = saved.json()["file"]["id"]
        fixed = owner.patch(f"{API_URL}/projects/{pid}/files/{fid}", json={"content": "def f():\n    pass\n"})
        assert fixed.status_code == 200
        assert owner.post(f"{API_URL}/projects/{pid}/analyze").status_code == 200

        assert any(p["id"] == pid for p in owner.get(f"{API_URL}/projects").json()["items"])
        history = owner.get(f"{API_URL}/history", params={"project_id": pid}).json()
        assert [e["event_type"] for e in history["items"]] == [
            "project.analyzed",
            "file.updated",
            "file.created",
            "project.created",
        ]

        # Another user cannot see or change any of it.
        for url in (
            f"/projects/{pid}",
            f"/projects/{pid}/files/{fid}",
            f"/history/{history['items'][0]['id']}",
        ):
            assert intruder.get(f"{API_URL}{url}").status_code == 404
        assert (
            intruder.patch(f"{API_URL}/projects/{pid}/files/{fid}", json={"content": "x"}).status_code == 404
        )
        assert intruder.get(f"{API_URL}/history").json()["total"] == 0

        # A cross-site write is refused even with a valid session.
        evil = owner.post(
            f"{API_URL}/projects", json={"name": "Evil"}, headers={"Origin": "https://evil.example"}
        )
        assert evil.status_code == 403

        assert owner.delete(f"{API_URL}/projects/{pid}").status_code == 204
        assert owner.post(f"{API_URL}/auth/logout").status_code == 204
        assert owner.get(f"{API_URL}/projects").status_code == 401
        assert owner.get(f"{API_URL}/history").status_code == 401
    finally:
        owner.close()
        intruder.close()


def test_frontend_serves_auth_and_app_routes(http: httpx.Client) -> None:
    for path in ("/login", "/register", "/app/coding", "/app/projects", "/app/history"):
        response = http.get(f"{FRONTEND_URL}{path}")
        assert response.status_code == 200, path
