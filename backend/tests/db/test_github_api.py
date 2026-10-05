"""Module 20: GitHub connection and repository import through the real API, client and database.

GitHub itself is replaced by a fake behind httpx's mock transport (the real GitHubClient code runs):
it checks the client secret and bearer token like GitHub would and serves a real ``.tar.gz``. No
real GitHub account, OAuth app or token is involved.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import tarfile
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import ActivityEvent, GitHubConnection, Project, ProjectSource
from app.services.github.client import GitHubClient
from tests.conftest import build_app
from tests.db.conftest import register

CLIENT_ID = "Iv1.testclient"
CLIENT_SECRET = "github-client-secret-for-tests"
TOKEN = "gho_" + "T" * 36
SHA = "a" * 40
REPO = {
    "id": 4242,
    "full_name": "octo/shop",
    "name": "shop",
    "owner": {"login": "octo"},
    "private": False,
    "default_branch": "main",
    "description": "A shop",
    "size": 12,
    "updated_at": "2026-10-01T00:00:00Z",
}


def tarball(files: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(f"octo-shop-{SHA[:7]}/{name}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        if symlink:
            info = tarfile.TarInfo(f"octo-shop-{SHA[:7]}/{symlink}")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../../../etc/passwd"
            tar.addfile(info)
    return buffer.getvalue()


REPOSITORY_FILES = {
    "shop/__init__.py": b"",
    "shop/cart.py": (
        b"from shop.pricing import price_of\n\n\ndef total(items):\n"
        b"    return sum(price_of(i) for i in items)\n"
    ),
    "shop/pricing.py": b"def price_of(item):\n    return item.price\n",
    "web/app.ts": b"export const answer: number = 42;\n",
    "README.md": b"# Shop\n",
    ".env": b"STRIPE_KEY=sk_live_should_never_be_stored\n",
    "config/credentials.json": b'{"password": "x"}',
    "node_modules/lib/index.js": b"module.exports = 1;\n",
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
    "../escape.py": b"print('outside')\n",
}


class FakeGitHub:
    def __init__(self) -> None:
        self.archive = tarball(REPOSITORY_FILES, symlink="shop/link.py")
        self.revoked: list[str] = []
        self.token_valid = True
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "github.com" and url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            if form.get("client_secret") != [CLIENT_SECRET] or form.get("code") != ["good-code"]:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": TOKEN, "scope": "", "token_type": "bearer"})
        if url.host == "codeload.github.com":
            assert "authorization" not in request.headers  # the bearer token stays on api.github.com
            return httpx.Response(200, content=self.archive)
        if url.host != "api.github.com":
            return httpx.Response(404)
        if url.path == f"/applications/{CLIENT_ID}/grant" and request.method == "DELETE":
            assert request.headers["authorization"].startswith("Basic ")
            self.revoked.append(json.loads(request.content)["access_token"])
            return httpx.Response(204)
        if request.headers.get("authorization") != f"Bearer {TOKEN}" or not self.token_valid:
            return httpx.Response(401, json={"message": "Bad credentials"})
        routes: dict[str, Any] = {
            "/user": {"id": 99, "login": "octo-dev"},
            "/user/repos": [REPO, {"id": "broken"}],
            "/repos/octo/shop": REPO,
            "/repos/octo/shop/branches": [{"name": "main"}, {"name": "feature/x"}],
            "/repos/octo/shop/branches/main": {"name": "main", "commit": {"sha": SHA}},
        }
        if url.path == f"/repos/octo/shop/tarball/{SHA}":
            return httpx.Response(
                302,
                headers={
                    "location": f"https://codeload.github.com/octo/shop/legacy.tar.gz/{SHA}?token=short-lived"
                },
            )
        if url.path in routes:
            return httpx.Response(200, json=routes[url.path])
        return httpx.Response(404, json={"message": "Not Found"})


def settings(**extra: Any) -> dict[str, Any]:
    return {
        "github_client_id": CLIENT_ID,
        "github_client_secret": CLIENT_SECRET,
        "github_callback_url": "http://testserver/api/v1/github/callback",
        "app_url": "http://frontend.test",
        "token_encryption_key": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        **extra,
    }


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def make_app(database_url: str, engine: Engine, github: FakeGitHub) -> Callable[..., FastAPI]:
    def factory(**extra: Any) -> FastAPI:
        app = build_app(database_url=database_url, **settings(**extra))
        app.state.github_client = GitHubClient(timeout_seconds=10, transport=httpx.MockTransport(github))
        return app

    return factory


def client(
    app: FastAPI, client_factory: Callable[[FastAPI], TestClient], email: str = "alice@example.com"
) -> TestClient:
    signed_in = client_factory(app)
    register(signed_in, email=email)
    return signed_in


def connect(api: TestClient, *, code: str = "good-code", state: str | None = None) -> Any:
    started = api.post("/api/v1/github/connect")
    assert started.status_code == 200, started.text
    authorize = urlsplit(started.json()["authorize_url"])
    query = parse_qs(authorize.query)
    assert authorize.netloc == "github.com"
    assert query["client_id"] == [CLIENT_ID]
    assert "scope" not in query  # public repositories only by default
    real_state = query["state"][0]
    return api.get(
        "/api/v1/github/callback", params={"code": code, "state": state or real_state}, follow_redirects=False
    )


def leaked(*texts: str) -> bool:
    return any(TOKEN in text or CLIENT_SECRET in text for text in texts)


# --- configuration and connection --------------------------------------------------------------


def test_not_configured(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client(build_app(database_url=database_url), client_factory)
    status = api.get("/api/v1/github/status").json()
    assert status["configured"] is False
    assert status["connected"] is False
    response = api.post("/api/v1/github/connect")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "github_not_configured"


def test_anonymous_users_cannot_use_any_endpoint(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], TestClient]
) -> None:
    anonymous = client_factory(make_app())
    for method, path in [
        ("GET", "/api/v1/github/status"),
        ("POST", "/api/v1/github/connect"),
        ("GET", "/api/v1/github/callback?code=good-code&state=x"),
        ("GET", "/api/v1/github/repositories"),
        ("DELETE", "/api/v1/github/connection"),
    ]:
        assert anonymous.request(method, path).status_code == 401, path
    assert (
        anonymous.post(
            "/api/v1/github/import", json={"owner": "octo", "repository": "shop", "branch": "main"}
        ).status_code
        == 401
    )


def test_oauth_connects_and_stores_the_token_only_encrypted(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = client(make_app(), client_factory)
    with caplog.at_level(logging.DEBUG):
        callback = connect(api)
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://frontend.test/app/uploads?github=connected"
    status = api.get("/api/v1/github/status").json()
    assert status["connected"] is True
    assert status["login"] == "octo-dev"
    assert status["private_repositories"] is False
    stored = session.scalars(select(GitHubConnection)).one()
    assert stored.token_ciphertext.startswith("v1.")
    assert TOKEN not in stored.token_ciphertext
    assert not leaked(json.dumps(status), callback.text, caplog.text)
    # The state cookie is single-use: replaying the callback fails.
    replay = api.get(
        "/api/v1/github/callback", params={"code": "good-code", "state": "x"}, follow_redirects=False
    )
    assert replay.headers["location"].endswith("github=github_oauth_state_invalid")


@pytest.mark.parametrize("attack", ["wrong_state", "no_cookie", "other_user_cookie", "bad_code"])
def test_oauth_state_and_code_are_checked(
    attack: str,
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    session: Session,
) -> None:
    app = make_app()
    api = client(app, client_factory)
    response: Any
    if attack == "wrong_state":
        response = connect(api, state="forged-state")
        expected = "github_oauth_state_invalid"
    elif attack == "no_cookie":
        api.post("/api/v1/github/connect")
        api.cookies.delete("codewalk_github_state", path="/api/v1/github/callback")
        response = api.get(
            "/api/v1/github/callback", params={"code": "good-code", "state": "s"}, follow_redirects=False
        )
        expected = "github_oauth_state_invalid"
    elif attack == "other_user_cookie":
        # Mallory starts a connection and tricks Alice into finishing it with Mallory's state.
        mallory = client(app, client_factory, email="mallory@example.com")
        started = mallory.post("/api/v1/github/connect")
        state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
        cookie = mallory.cookies.get("codewalk_github_state", path="/api/v1/github/callback")
        assert cookie is not None
        api.cookies.set("codewalk_github_state", cookie, path="/api/v1/github/callback")
        response = api.get(
            "/api/v1/github/callback", params={"code": "good-code", "state": state}, follow_redirects=False
        )
        expected = "github_oauth_state_invalid"
    else:
        response = connect(api, code="stolen-or-expired")
        expected = "github_oauth_failed"
    assert response.status_code == 303
    assert response.headers["location"] == f"http://frontend.test/app/uploads?github={expected}"
    assert session.scalars(select(GitHubConnection)).all() == []


# --- browsing and import ---------------------------------------------------------------------


def test_repositories_and_branches(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client(make_app(), client_factory)
    assert api.get("/api/v1/github/repositories").json()["error"]["code"] == "github_not_connected"
    connect(api)
    repositories = api.get("/api/v1/github/repositories").json()
    assert [r["full_name"] for r in repositories["items"]] == ["octo/shop"]  # the malformed entry is left out
    assert repositories["has_more"] is False
    branches = api.get("/api/v1/github/repositories/octo/shop/branches").json()
    assert branches["items"] == ["main", "feature/x"]
    assert api.get("/api/v1/github/repositories/octo/sh%2Fop/branches").status_code in (404, 422)
    assert not leaked(json.dumps(repositories), json.dumps(branches))


def test_import_creates_an_owned_project_and_skips_unsafe_files(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = make_app()
    api = client(app, client_factory)
    connect(api)
    with caplog.at_level(logging.DEBUG):
        response = api.post(
            "/api/v1/github/import", json={"owner": "octo", "repository": "shop", "branch": "main"}
        )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["project_name"] == "shop"
    assert result["commit_sha"] == SHA
    assert result["repository"] == "octo/shop"
    assert result["files_imported"] == 5
    assert result["indexing"] == "completed"
    assert result["indexed_files"] == 5
    reasons = {item["path"]: item["reason"] for item in result["skipped"]}
    assert reasons == {
        ".env": "secret",
        "config/credentials.json": "secret",
        "node_modules/lib/index.js": "ignored",
        "assets/logo.png": "binary",
        "shop/link.py": "symlink",
        "../escape.py": "invalid_path",
    }
    project_id = result["project_id"]
    files = api.get(f"/api/v1/projects/{project_id}/files").json()["items"]
    assert sorted(f["path"] for f in files) == [
        "README.md",
        "shop/__init__.py",
        "shop/cart.py",
        "shop/pricing.py",
        "web/app.ts",
    ]
    project = session.get(Project, project_id)
    assert project is not None
    assert project.origin.value == "upload"
    source = session.scalars(select(ProjectSource)).one()
    assert (source.full_name, source.branch, source.commit_sha, source.files_imported) == (
        "octo/shop",
        "main",
        SHA,
        5,
    )
    event = session.scalars(select(ActivityEvent).where(ActivityEvent.event_type == "github.imported")).one()
    assert event.details["repository"] == "octo/shop"
    every_file = json.dumps([api.get(f"/api/v1/projects/{project_id}/files/{f['id']}").json() for f in files])
    assert "sk_live_should_never_be_stored" not in every_file
    assert not leaked(response.text, every_file, caplog.text, json.dumps(event.details))

    # Another user cannot see the imported project, and cannot import with Alice's connection.
    mallory = client(app, client_factory, email="mallory@example.com")
    assert mallory.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert mallory.get("/api/v1/github/status").json()["connected"] is False
    denied = mallory.post(
        "/api/v1/github/import", json={"owner": "octo", "repository": "shop", "branch": "main"}
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "github_not_connected"


def test_duplicate_import_is_refused(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client(make_app(), client_factory)
    connect(api)
    body = {"owner": "octo", "repository": "shop", "branch": "main"}
    assert api.post("/api/v1/github/import", json=body).status_code == 201
    again = api.post("/api/v1/github/import", json={**body, "project_name": "Shop copy"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "github_repository_already_imported"


def test_oversized_repository_is_refused_before_anything_is_stored(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    github: FakeGitHub,
    session: Session,
) -> None:
    github.archive = tarball({"blob.bin": os.urandom(1_200_000)})  # incompressible: > 1 MiB as .tar.gz
    api = client(make_app(github_max_archive_bytes=1024 * 1024), client_factory)
    connect(api)
    response = api.post(
        "/api/v1/github/import", json={"owner": "octo", "repository": "shop", "branch": "main"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "github_repository_too_large"
    assert session.scalars(select(Project)).all() == []


def test_unknown_branch_and_rate_limit(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], TestClient]
) -> None:
    api = client(make_app(github_import_max_runs=2), client_factory)
    connect(api)
    missing = api.post(
        "/api/v1/github/import", json={"owner": "octo", "repository": "shop", "branch": "nope"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "github_not_found"
    body = {"owner": "octo", "repository": "shop", "branch": "main"}
    assert api.post("/api/v1/github/import", json=body).status_code == 201
    limited = api.post("/api/v1/github/import", json=body)
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


# --- disconnect and revocation ----------------------------------------------------------------


def test_disconnect_revokes_the_grant_and_forgets_the_token(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    github: FakeGitHub,
    session: Session,
) -> None:
    api = client(make_app(), client_factory)
    connect(api)
    assert api.delete("/api/v1/github/connection").status_code == 204
    assert github.revoked == [TOKEN]
    assert session.scalars(select(GitHubConnection)).all() == []
    assert api.get("/api/v1/github/status").json()["connected"] is False
    assert api.delete("/api/v1/github/connection").status_code == 204  # idempotent


def test_a_token_revoked_at_github_is_forgotten(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    github: FakeGitHub,
    session: Session,
) -> None:
    api = client(make_app(), client_factory)
    connect(api)
    github.token_valid = False
    response = api.get("/api/v1/github/repositories")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "github_reauthorization_required"
    assert session.scalars(select(GitHubConnection)).all() == []


def test_a_changed_encryption_key_requires_reconnecting(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], TestClient],
    database_url: str,
    github: FakeGitHub,
) -> None:
    api = client(make_app(), client_factory)
    connect(api)
    other = make_app()  # same database, a different key and no old keys
    other.state.github_client = GitHubClient(timeout_seconds=10, transport=httpx.MockTransport(github))
    cookie = api.cookies.get("codewalk_session")
    assert cookie is not None
    second = client_factory(other)
    second.cookies.set("codewalk_session", cookie)
    response = second.get("/api/v1/github/repositories")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "github_reauthorization_required"
    assert not leaked(response.text)
