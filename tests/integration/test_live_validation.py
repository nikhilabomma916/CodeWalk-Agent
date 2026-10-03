"""Module 14 production validation against the running stack (real HTTP, real database).

Start the stack first (``npm run dev``, or the backend container plus ``npm run dev:frontend``),
then ``npm run test:integration``. These tests fail rather than skip when the stack is down.

They adapt to the server's configuration and never fake a provider: when AI or semantic
retrieval is not configured, they assert the real "unavailable" behavior; the configured
paths are covered by the optional live-provider tests in ``backend/tests``.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator

import httpx
import pytest

API_URL = os.environ.get("CODEWALK_STACK_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
FRONTEND_ORIGIN = os.environ.get("CODEWALK_STACK_FRONTEND_ORIGIN", "http://localhost:3000")
PASSWORD = "live-validation-Pass-7"
FAKE_KEY = "AKIAFAKEFAKEFAKEFAKE"


def _client(label: str) -> httpx.Client:
    client = httpx.Client(base_url=API_URL, timeout=60.0, headers={"Origin": FRONTEND_ORIGIN})
    email = f"m14-{label}-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/register", json={"email": email, "name": label.title(), "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return client


@pytest.fixture(scope="module")
def users() -> Iterator[tuple[httpx.Client, httpx.Client, httpx.Client]]:
    owner, other = _client("owner"), _client("other")
    anonymous = httpx.Client(base_url=API_URL, timeout=30.0, headers={"Origin": FRONTEND_ORIGIN})
    yield owner, other, anonymous
    for client in (owner, other, anonymous):
        client.close()


@pytest.fixture(scope="module")
def project(users: tuple[httpx.Client, httpx.Client, httpx.Client]) -> dict[str, str]:
    owner = users[0]
    pid = owner.post("/projects", json={"name": "Module 14 live"}).json()["id"]
    files = {
        "shop/pricing.py": "def price_of(item):\n    return item.price\n",
        "shop/cart.py": (
            "from shop.pricing import price_of\n\n\n"
            "def cart_total(items):\n"
            "    return sum(price_of(i) for i in items)\n"
        ),
    }
    ids = {}
    for path, content in files.items():
        response = owner.post(f"/projects/{pid}/files", json={"path": path, "content": content})
        assert response.status_code == 201, response.text
        ids[path] = response.json()["file"]["id"]
    return {"id": pid, "cart": ids["shop/cart.py"]}


def test_core_workflow(users: tuple[httpx.Client, ...], project: dict[str, str]) -> None:
    owner = users[0]
    pid = project["id"]
    broken = owner.patch(f"/projects/{pid}/files/{project['cart']}", json={"content": "def cart_total(:\n"})
    assert broken.json()["analysis"]["diagnostic_count"] >= 1
    restored = owner.patch(
        f"/projects/{pid}/files/{project['cart']}",
        json={"content": "from shop.pricing import price_of\n\n\ndef cart_total(items):\n    return 0\n"},
    )
    assert restored.status_code == 200
    report = owner.post(f"/projects/{pid}/analyze").json()
    assert report["statistics"]["total_files"] == 2
    top = owner.post(f"/projects/{pid}/search", json={"query": "price_of"}).json()["results"][0]
    assert (top["file_path"], top["line"]) == ("shop/pricing.py", 1)
    context = owner.post(f"/projects/{pid}/context", json={"current_file": "shop/cart.py"}).json()
    assert any(s["file_path"] == "shop/pricing.py" for s in context["snippets"])
    versions = owner.get(f"/projects/{pid}/files/{project['cart']}/versions").json()
    assert versions["total"] == 3


def test_ai_agent_and_rag_report_their_real_state(
    users: tuple[httpx.Client, ...], project: dict[str, str]
) -> None:
    owner = users[0]
    ai = owner.get("/ai/status").json()
    agent = owner.get("/agent/status").json()
    rag = owner.get("/rag/status").json()
    assert agent["available"] == ai["available"]  # the agent runs on the AI provider
    assert len(agent["tools"]) == 9
    if not ai["available"]:
        run = owner.post(
            "/agent/run", json={"project_id": project["id"], "message": "What does cart_total do?"}
        )
        assert run.status_code == 503
        assert run.json()["error"]["code"] in {"ai_disabled", "ai_not_configured"}
        explain = owner.post(
            "/ai/explain",
            json={
                "code": "x = y\n",
                "file_path": "a.py",
                "diagnostic": {
                    "id": "d1",
                    "severity": "error",
                    "message": "Undefined name `y`",
                    "source": "ruff",
                    "line": 1,
                    "column": 5,
                    "end_line": 1,
                    "end_column": 6,
                },
            },
        )
        assert explain.status_code == 503
    if not rag["available"]:
        hybrid = owner.post(
            f"/projects/{project['id']}/search", json={"query": "price_of", "mode": "hybrid"}
        ).json()
        assert hybrid["mode_used"] == "deterministic"
        assert hybrid["warnings"]
        assert all(r["match_type"] != "semantic" for r in hybrid["results"])
        assert owner.post(f"/projects/{project['id']}/rag/index").status_code == 503
    # Status responses may name a missing setting, but never carry a credential value.
    for body in (ai, agent, rag):
        assert not re.search(r"sk-ant-[A-Za-z0-9_-]{8,}|pa-[A-Za-z0-9_-]{20,}", str(body))


def test_cross_user_isolation(users: tuple[httpx.Client, ...], project: dict[str, str]) -> None:
    _, other, anonymous = users
    pid, fid = project["id"], project["cart"]
    for method, path, body in (
        ("get", f"/projects/{pid}", None),
        ("get", f"/projects/{pid}/files/{fid}", None),
        ("patch", f"/projects/{pid}/files/{fid}", {"content": "pwned = 1\n"}),
        ("post", f"/projects/{pid}/search", {"query": "price_of"}),
        ("post", f"/projects/{pid}/context", {"current_file": "shop/cart.py"}),
        ("get", f"/projects/{pid}/rag/index", None),
        ("get", f"/agent/runs/{uuid.uuid4()}", None),
        ("post", f"/agent/actions/{uuid.uuid4()}/approve", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        stolen = getattr(other, method)(path, **kwargs)
        assert stolen.status_code == 404, (path, stolen.status_code)
        assert "price_of" not in stolen.text
        assert getattr(anonymous, method)(path, **kwargs).status_code == 401, path


def test_paths_secrets_origins_and_headers(users: tuple[httpx.Client, ...], project: dict[str, str]) -> None:
    owner = users[0]
    for path in ("../x.py", "/etc/passwd", "C:/Windows/win.ini", ".env", ".aws/credentials", "secrets.yaml"):
        response = owner.post(
            f"/projects/{project['id']}/files", json={"path": path, "content": f"k={FAKE_KEY}"}
        )
        assert response.status_code == 422, path
        assert FAKE_KEY not in response.text
    forged = owner.post("/projects", json={"name": "csrf"}, headers={"Origin": "https://evil.example"})
    assert forged.status_code == 403
    headers = owner.get("/projects").headers
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    too_big = owner.post(
        "/analysis/code", content=b"x" * (16 * 1024 * 1024), headers={"Content-Type": "application/json"}
    )
    assert too_big.status_code == 413
