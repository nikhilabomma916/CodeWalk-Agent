"""Deployment smoke test (Module 15): real HTTP through the reverse proxy of a running stack.

    docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait
    CODEWALK_SMOKE_URL=https://codewalk.example.com npm run test:smoke

Every check talks to the real proxy, frontend, backend and database; nothing is mocked. Optional
providers are never faked: without keys the real "unavailable" behavior is asserted.

Persistence: with CODEWALK_SMOKE_STATE set, the first run stores a test account and file there and
a later run (after a restart) verifies they survived. scripts/deploy-lifecycle.mjs does both.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("CODEWALK_SMOKE_URL", "http://127.0.0.1:8080").rstrip("/")
API = f"{BASE_URL}/api/v1"
STATE_FILE = os.environ.get("CODEWALK_SMOKE_STATE")
COOKIE = "codewalk_session"
BROKEN_PYTHON = "def total(items):\n    return sum(item.price for item in items\n"


def _client() -> httpx.Client:
    # Browsers send Origin on state-changing requests; the proxy origin is the app's own origin.
    return httpx.Client(timeout=30.0, headers={"Origin": BASE_URL}, follow_redirects=False)


def _session_from(response: httpx.Response) -> str:
    """The session cookie, after checking its flags. Sent manually: a Python client will not
    send a Secure cookie over plain-HTTP localhost, which browsers do."""
    header = next(
        (
            value
            for key, value in response.headers.multi_items()
            if key == "set-cookie" and value.startswith(f"{COOKIE}=")
        ),
        None,
    )
    assert header, f"no session cookie in {response.status_code} response"
    flags = {part.strip().lower() for part in header.split(";")[1:]}
    assert "httponly" in flags
    assert "samesite=lax" in flags
    assert "path=/" in flags
    assert "secure" in flags, "production session cookies must be Secure"
    return header.split(";", 1)[0].split("=", 1)[1]


def _signed_in(email: str, password: str, *, register: bool) -> httpx.Client:
    client = _client()
    if register:
        response = client.post(
            f"{API}/auth/register", json={"email": email, "name": "Smoke", "password": password}
        )
        assert response.status_code == 201, response.text
    else:
        response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
    client.headers["Cookie"] = f"{COOKIE}={_session_from(response)}"
    return client


@pytest.fixture(scope="module")
def account() -> Iterator[tuple[httpx.Client, str, str]]:
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    password = f"Smoke-{uuid.uuid4().hex}"
    client = _signed_in(email, password, register=True)
    yield client, email, password
    client.close()


def test_proxy_frontend_and_csp() -> None:
    with _client() as client:
        assert client.get(f"{BASE_URL}/nginx-health").json() == {"status": "ok"}
        page = client.get(f"{BASE_URL}/login")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        policy = page.headers["content-security-policy"]
        nonce = re.search(r"'nonce-([^']+)'", policy)
        assert nonce, policy
        assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
        assert "frame-ancestors 'none'" in policy
        # Next.js attached this request's nonce to its scripts (the CSP would block them otherwise).
        assert f'nonce="{nonce.group(1)}"' in page.text
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
        assert "x-powered-by" not in page.headers
        assert page.headers.get("server") == "nginx"  # no version disclosed
        # The editor is served by this origin (no CDN), as the CSP requires.
        assert client.get(f"{BASE_URL}/monaco/vs/loader.js").status_code == 200
        # Protected pages are client-side guarded; the shell itself renders.
        assert client.get(f"{BASE_URL}/app/projects").status_code == 200


def test_backend_health_through_proxy() -> None:
    with _client() as client:
        live = client.get(f"{API}/health/live")
        assert live.status_code == 200
        assert live.json() == {"status": "ok"}
        ready = client.get(f"{API}/health/ready")
        assert ready.status_code == 200
        body = ready.json()
        assert body["status"] == "ok"
        assert body["environment"] == "production"
        database = next(check for check in body["checks"] if check["name"] == "database")
        assert database["status"] == "pass"
        assert database["required"] is True
        assert ready.headers["cache-control"] == "no-store"
        assert ready.headers["content-security-policy"].startswith("default-src 'none'")
        assert "content-encoding" not in ready.headers  # API responses are never compressed
        # Interactive docs are off in production and are not routed.
        assert client.get(f"{BASE_URL}/docs").status_code == 404
        assert client.get(f"{API}/openapi.json").status_code == 404
        missing = client.get(f"{API}/no-such-route")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        # Backend metrics are served outside /api and only on the internal network (not proxied).
        exposed = client.get(f"{BASE_URL}/metrics")
        assert "codewalk_http_request_duration_seconds" not in exposed.text
        assert client.get(f"{API}/metrics").status_code == 404


def test_authentication_and_origin_checks(account: tuple[httpx.Client, str, str]) -> None:
    client, email, password = account
    me = client.get(f"{API}/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email
    with _client() as anonymous:
        assert anonymous.get(f"{API}/auth/me").status_code == 401
        wrong = anonymous.post(f"{API}/auth/login", json={"email": email, "password": password + "x"})
        assert wrong.status_code == 401
        # A foreign site cannot use the API: its state-changing requests are refused...
        foreign = anonymous.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
            headers={"Origin": "https://evil.example"},
        )
        assert foreign.status_code == 403
        assert foreign.json()["error"]["code"] == "origin_not_allowed"
        # ...and CORS grants it nothing.
        preflight = anonymous.options(
            f"{API}/projects",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in preflight.headers
        # A cross-origin read is allowed by the browser only with a matching Allow-Origin header.
        read = anonymous.get(f"{API}/health/live", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in read.headers


def test_projects_diagnostics_and_search(account: tuple[httpx.Client, str, str]) -> None:
    client = account[0]
    project = client.post(f"{API}/projects", json={"name": "Smoke project"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    created = client.post(
        f"{API}/projects/{pid}/files", json={"path": "shop/cart.py", "content": BROKEN_PYTHON}
    )
    assert created.status_code == 201, created.text
    # Saving runs the real analyzers: the syntax error is reported with its location.
    analysis = created.json()["analysis"]
    assert analysis["diagnostic_count"] >= 1
    search = client.post(f"{API}/projects/{pid}/search", json={"query": "total"})
    assert search.status_code == 200
    assert search.json()["results"][0]["file_path"] == "shop/cart.py"
    listed = client.get(f"{API}/projects").json()
    assert any(item["id"] == pid for item in listed["items"])
    # TypeScript diagnostics come from the Node worker inside the backend image.
    ts = client.post(
        f"{API}/analysis/code", json={"code": "const x: number = 'a';\n", "language": "typescript"}
    )
    assert ts.status_code == 200
    assert any(d["severity"] == "error" for d in ts.json()["diagnostics"])


def test_optional_providers_report_unavailable_without_keys(account: tuple[httpx.Client, str, str]) -> None:
    client = account[0]
    ai = client.get(f"{API}/ai/status").json()
    agent = client.get(f"{API}/agent/status").json()
    rag = client.get(f"{API}/rag/status").json()
    if not ai["available"]:
        assert agent["available"] is False
        explain = client.post(f"{API}/agent/run", json={"project_id": str(uuid.uuid4()), "message": "hi"})
        assert explain.status_code in {404, 503}  # unknown project, or the agent is unavailable
    if not rag["available"]:
        assert rag["available"] is False
    for body in (ai, agent, rag):
        assert not re.search(r"sk-ant-[A-Za-z0-9_-]{8,}|pa-[A-Za-z0-9_-]{20,}", json.dumps(body))


def test_request_size_limits() -> None:
    with _client() as client:
        # Above the backend's 6 MiB limit: the backend answers with its JSON 413.
        backend = client.post(
            f"{API}/analysis/code",
            content=b"x" * (7 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert backend.status_code == 413
        assert backend.json()["error"]["code"] == "payload_too_large"
        # Above the proxy's 8 MiB cap: refused at the proxy, same error shape.
        proxy = client.post(
            f"{API}/analysis/code",
            content=b"x" * (9 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert proxy.status_code == 413
        assert proxy.json()["error"]["code"] == "payload_too_large"


def test_data_persists_across_restarts() -> None:
    """First run (no state file yet): store an account and file. Next run: verify they survived."""
    if not STATE_FILE:
        pytest.skip("CODEWALK_SMOKE_STATE is not set (used by scripts/deploy-lifecycle.mjs)")
    state_path = Path(STATE_FILE)
    if not state_path.exists():
        email = f"persist-{uuid.uuid4().hex[:12]}@example.com"
        password = f"Persist-{uuid.uuid4().hex}"
        content = f"MARKER = '{uuid.uuid4().hex}'\n"
        client = _signed_in(email, password, register=True)
        try:
            pid = client.post(f"{API}/projects", json={"name": "Persistence check"}).json()["id"]
            file = client.post(f"{API}/projects/{pid}/files", json={"path": "marker.py", "content": content})
            assert file.status_code == 201, file.text
            fid = file.json()["file"]["id"]
        finally:
            client.close()
        state_path.write_text(
            json.dumps(
                {"email": email, "password": password, "project": pid, "file": fid, "content": content}
            ),
            encoding="utf-8",
        )
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    client = _signed_in(state["email"], state["password"], register=False)
    try:
        stored = client.get(f"{API}/projects/{state['project']}/files/{state['file']}")
        assert stored.status_code == 200, stored.text
        assert stored.json()["content"] == state["content"]
    finally:
        client.close()
