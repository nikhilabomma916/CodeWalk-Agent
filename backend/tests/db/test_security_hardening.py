"""Module 21: security regression tests that cover every route automatically, and shared limits.

The route sweeps read the application's own OpenAPI document, so a route added later is covered
without editing this file: every operation must reject anonymous callers (except the documented
public ones), and every project-, file-, run- or action-scoped operation must refuse another user's
identifiers without revealing anything about them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import RateLimitEvent
from tests.conftest import build_app
from tests.db.conftest import TEST_PASSWORD, register

# Reachable without signing in, by design.
PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/api/v1/info"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/ai/status"),
    ("GET", "/api/v1/retrieval/status"),
    ("GET", "/api/v1/analysis/languages"),
    ("POST", "/api/v1/analysis/code"),
}
SECRET_CONTENT = "TOP_SECRET_MARKER = 'alice-only-0425'\n"


def operations(app: FastAPI) -> Iterator[tuple[str, str]]:
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                yield method.upper(), path


def fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


@pytest.fixture
def app(database_url: str, engine: Engine) -> FastAPI:
    return build_app(database_url=database_url)


def signed_in(app: FastAPI, client_factory: Callable[[FastAPI], TestClient], email: str) -> TestClient:
    client = client_factory(app)
    register(client, email=email)
    return client


def test_every_non_public_operation_requires_a_session(
    app: FastAPI, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    anonymous = client_factory(app)
    checked = 0
    for method, path in operations(app):
        if (method, path) in PUBLIC:
            continue
        url = fill(path, {"owner": "octo", "repository": "shop"})
        response = anonymous.request(method, url, json={} if method in {"POST", "PUT", "PATCH"} else None)
        assert response.status_code == 401, (method, path, response.status_code, response.text[:200])
        checked += 1
    assert checked > 40  # the sweep really covered the API


def test_no_operation_reveals_or_changes_another_users_project(
    app: FastAPI, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    alice = signed_in(app, client_factory, "alice@example.com")
    project = alice.post("/api/v1/projects", json={"name": "Alice private project"}).json()
    created = alice.post(
        f"/api/v1/projects/{project['id']}/files", json={"path": "secret/plan.py", "content": SECRET_CONTENT}
    ).json()
    file_id = created["file"]["id"]
    analysis_id = (created.get("analysis") or {}).get("id") or str(uuid.uuid4())
    ids = {"project_id": project["id"], "file_id": file_id, "analysis_id": analysis_id, "id": file_id}

    mallory = signed_in(app, client_factory, "mallory@example.com")
    scoped = [
        (m, p)
        for m, p in operations(app)
        if any(f"{{{name}}}" in p for name in ("project_id", "file_id", "analysis_id"))
    ]
    assert len(scoped) > 20
    for method, path in scoped:
        response = mallory.request(
            method, fill(path, ids), json={} if method in {"POST", "PUT", "PATCH"} else None
        )
        assert response.status_code in {404, 422}, (method, path, response.status_code, response.text[:200])
        assert "alice-only-0425" not in response.text
        assert "Alice private project" not in response.text

    # Nothing of Alice's changed.
    assert alice.get(f"/api/v1/projects/{project['id']}").json()["name"] == "Alice private project"
    detail = alice.get(f"/api/v1/projects/{project['id']}/files/{file_id}").json()
    assert detail["content"] == SECRET_CONTENT
    assert (
        detail["content_hash"]
        == alice.get(f"/api/v1/projects/{project['id']}/files").json()["items"][0]["content_hash"]
    )
    assert len(alice.get(f"/api/v1/projects/{project['id']}/files/{file_id}/versions").json()["items"]) == 1


# --- shared limits across API instances ------------------------------------------------------------


def test_login_limit_is_shared_by_every_instance(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient], session: Session
) -> None:
    """Two app instances (two serverless instances) on one database share one login limit."""
    first = build_app(database_url=database_url, login_max_attempts=3)
    second = build_app(database_url=database_url, login_max_attempts=3)
    register(client_factory(first), email="victim@example.com")
    attempts = [client_factory(first), client_factory(second)]
    statuses = [
        attempts[i % 2]
        .post("/api/v1/auth/login", json={"email": "victim@example.com", "password": "wrong" * 3})
        .status_code
        for i in range(4)
    ]
    assert statuses == [401, 401, 401, 429]
    # Only hashes are stored: no address or email address in the table.
    keys = session.scalars(select(RateLimitEvent.key_hash)).all()
    assert keys
    assert all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys)


def test_account_limit_applies_across_addresses(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app = build_app(database_url=database_url, login_max_attempts=100, login_account_max_attempts=3)
    register(client_factory(app), email="target@example.com")
    statuses = []
    for i in range(4):
        client = TestClient(app, client=(f"203.0.113.{i}", 4000 + i))
        statuses.append(
            client.post(
                "/api/v1/auth/login", json={"email": "target@example.com", "password": "wrong" * 3}
            ).status_code
        )
    assert statuses == [401, 401, 401, 429]
    # A different account is unaffected.
    assert (
        TestClient(app, client=("203.0.113.9", 4100))
        .post("/api/v1/auth/login", json={"email": "other@example.com", "password": "wrong" * 3})
        .status_code
        == 401
    )


def test_successful_login_clears_the_counts(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient], session: Session
) -> None:
    app = build_app(database_url=database_url, login_max_attempts=3)
    register(client_factory(app), email="me@example.com")
    client = client_factory(app)
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "me@example.com", "password": "wrong" * 3}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "me@example.com", "password": TEST_PASSWORD}
        ).status_code
        == 200
    )
    for _ in range(2):  # the earlier failures no longer count
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "me@example.com", "password": "wrong" * 3}
            ).status_code
            == 401
        )
    assert (
        session.scalar(select(func.count()).select_from(RateLimitEvent)) == 1 + 2 * 2
    )  # registration, then address + account


# --- deceptive names ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "invoice" + chr(0x202E) + "gpj.py",
        "a" + chr(0x200B) + "b.py",
        "line" + chr(0x2028) + "break.py",
        "dir/ name.py",
        "dir/name.py ",
        "c1\u0085.py",
    ],
)
def test_deceptive_file_paths_are_refused(
    path: str, app: FastAPI, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = signed_in(app, client_factory, "alice@example.com")
    project = api.post("/api/v1/projects", json={"name": "P"}).json()
    response = api.post(f"/api/v1/projects/{project['id']}/files", json={"path": path, "content": "x"})
    assert response.status_code == 422, response.text
    imported = api.post(
        f"/api/v1/projects/{project['id']}/files/import", json={"files": [{"path": path, "content": "x"}]}
    )
    assert imported.status_code == 200
    assert [s["reason"] for s in imported.json()["skipped"]] == ["invalid_path"]


def test_unicode_names_that_are_not_deceptive_still_work(
    app: FastAPI, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = signed_in(app, client_factory, "alice@example.com")
    project = api.post("/api/v1/projects", json={"name": "Café ünïcode 项目"}).json()
    response = api.post(
        f"/api/v1/projects/{project['id']}/files", json={"path": "docs/résumé 项目.md", "content": "x"}
    )
    assert response.status_code == 201, response.text
