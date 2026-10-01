"""Registration, login, logout, sessions, and request protections against real PostgreSQL."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import AuthSession, User
from tests.conftest import FRONTEND_ORIGIN, build_app
from tests.db.conftest import TEST_PASSWORD, register

COOKIE = "codewalk_session"


def login(client: TestClient, email: str = "alice@example.com", password: str = TEST_PASSWORD) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


# --- Registration ----------------------------------------------------------------


def test_register_signs_in_and_never_exposes_the_password(anonymous: TestClient, session: Session) -> None:
    response = anonymous.post(
        "/api/v1/auth/register",
        json={"email": "  Alice@Example.COM ", "name": " Alice ", "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "email", "created_at", "last_login_at"}
    assert body["email"] == "alice@example.com"  # normalized
    assert body["name"] == "Alice"
    assert TEST_PASSWORD not in response.text
    assert "hash" not in response.text

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # off outside production (plain-http localhost)
    assert anonymous.get("/api/v1/auth/me").json()["email"] == "alice@example.com"

    stored = session.scalars(select(User)).one()
    assert stored.password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in stored.password_hash
    # Only a hash of the session token is stored.
    token = anonymous.cookies.get(COOKIE)
    assert token is not None
    assert session.scalar(select(AuthSession.token_hash)) != token


def test_duplicate_email_is_rejected_case_insensitively(anonymous: TestClient) -> None:
    register(anonymous)
    response = anonymous.post(
        "/api/v1/auth/register",
        json={"email": "ALICE@example.com", "name": "Imposter", "password": "another-pass-9"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short1!", "at least 8 characters"),
        ("onlyletters", "number or symbol"),
        ("1234567890", "at least one letter"),
        ("        ", "whitespace"),
        ("aaaa1111", "too repetitive"),
        ("x" * 120 + "1234567890", "at most 128 characters"),
    ],
)
def test_weak_passwords_are_rejected(anonymous: TestClient, password: str, reason: str) -> None:
    response = anonymous.post(
        "/api/v1/auth/register", json={"email": "bob@example.com", "name": "Bob", "password": password}
    )
    assert response.status_code == 422
    assert reason in response.text
    assert password not in response.text  # submitted values are never echoed


def test_password_must_differ_from_email(anonymous: TestClient) -> None:
    response = anonymous.post(
        "/api/v1/auth/register",
        json={"email": "bob123@example.com", "name": "Bob", "password": "BOB123@example.com"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "name": "Bob", "password": TEST_PASSWORD},
        {"email": "bob@example.com", "name": "", "password": TEST_PASSWORD},
        {"email": "bob@example.com", "password": TEST_PASSWORD},
        {"email": "bob@example.com", "name": "Bob", "password": TEST_PASSWORD, "is_active": False},
    ],
)
def test_invalid_registration_payloads(anonymous: TestClient, payload: dict[str, object]) -> None:
    assert anonymous.post("/api/v1/auth/register", json=payload).status_code == 422


def test_malformed_json_is_rejected(anonymous: TestClient) -> None:
    response = anonymous.post(
        "/api/v1/auth/login", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Login / logout --------------------------------------------------------------


def test_login_success_starts_a_new_session(db_app: FastAPI) -> None:
    with TestClient(db_app) as first:
        register(first)
    with TestClient(db_app) as second:
        assert second.get("/api/v1/auth/me").status_code == 401
        response = second.post(
            "/api/v1/auth/login", json={"email": "ALICE@example.com", "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["last_login_at"] is not None
        assert "HttpOnly" in response.headers["set-cookie"]
        assert second.get("/api/v1/auth/me").status_code == 200


def test_wrong_password_and_unknown_email_look_the_same(anonymous: TestClient) -> None:
    register(anonymous)
    anonymous.post("/api/v1/auth/logout")
    wrong = anonymous.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "nope-nope-1"}
    )
    unknown = anonymous.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "nope-nope-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "set-cookie" not in wrong.headers


def test_logout_ends_the_session(anonymous: TestClient) -> None:
    register(anonymous)
    token = anonymous.cookies.get(COOKIE)
    response = anonymous.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert f'{COOKIE}=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    assert anonymous.get("/api/v1/auth/me").status_code == 401

    # The old token is no longer accepted even if a client kept it.
    anonymous.cookies.set(COOKIE, token or "")
    assert anonymous.get("/api/v1/auth/me").status_code == 401
    # Logging out again (or while signed out) is harmless.
    assert anonymous.post("/api/v1/auth/logout").status_code == 204


def test_unauthenticated_and_forged_sessions(anonymous: TestClient) -> None:
    response = anonymous.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    for forged in ("a" * 43, "short", "../../etc/passwd", "t%C3%B6k%C3%A9n" * 4):
        anonymous.cookies.set(COOKIE, forged)
        assert anonymous.get("/api/v1/auth/me").status_code == 401
        assert anonymous.post("/api/v1/auth/logout").status_code == 204


def test_expired_session_is_rejected(api: TestClient, engine: Engine) -> None:
    assert api.get("/api/v1/auth/me").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 minute'"))
    response = api.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_expired_sessions_are_cleaned_up_on_login(api: TestClient, session: Session) -> None:
    session.execute(
        text("UPDATE auth_sessions SET expires_at = :past"), {"past": datetime.now(UTC) - timedelta(days=1)}
    )
    session.commit()
    login(api)
    assert session.scalar(text("SELECT count(*) FROM auth_sessions")) == 1


def test_disabled_account(api: TestClient, engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET is_active = false"))
    # Existing sessions stop working...
    assert api.get("/api/v1/auth/me").status_code == 401
    # ...and a correct password is answered with account_disabled (a wrong one stays generic).
    response = api.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"
    wrong = api.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "nope-nope-1"})
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_secure_cookie_when_configured(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    client = client_factory(build_app(database_url=database_url, session_cookie_secure=True))
    response = client.post(
        "/api/v1/auth/register", json={"email": "sec@example.com", "name": "Sec", "password": TEST_PASSWORD}
    )
    assert "Secure" in response.headers["set-cookie"]


# --- Abuse protections -------------------------------------------------------------


def test_failed_logins_are_rate_limited(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    client = client_factory(build_app(database_url=database_url, login_max_attempts=3))
    register(client)
    bad = {"email": "alice@example.com", "password": "wrong-pass-1"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=bad).status_code == 401
    limited = client.post("/api/v1/auth/login", json=bad)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "too_many_attempts"
    assert int(limited.headers["Retry-After"]) > 0
    # Even the right password waits until the window passes.
    assert client.post("/api/v1/auth/login", json={**bad, "password": TEST_PASSWORD}).status_code == 429


def test_registrations_are_rate_limited(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    client = client_factory(build_app(database_url=database_url, register_max_attempts=2))
    for index in range(2):
        register(client, email=f"user{index}@example.com")
    response = client.post(
        "/api/v1/auth/register", json={"email": "user9@example.com", "name": "U", "password": TEST_PASSWORD}
    )
    assert response.status_code == 429


def test_cross_site_requests_are_rejected(api: TestClient) -> None:
    evil = api.post("/api/v1/projects", json={"name": "Evil"}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert evil.json()["error"]["code"] == "origin_not_allowed"
    assert api.get("/api/v1/projects").json()["total"] == 0

    allowed = api.post("/api/v1/projects", json={"name": "Fine"}, headers={"Origin": FRONTEND_ORIGIN})
    assert allowed.status_code == 201
    # Reads are not state-changing and are governed by CORS instead.
    assert api.get("/api/v1/projects", headers={"Origin": "https://evil.example"}).status_code == 200


def test_credentials_are_never_logged(anonymous: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        register(anonymous)
        anonymous.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-pass-1"})
        login(anonymous)
    token = anonymous.cookies.get(COOKIE) or "missing"
    assert TEST_PASSWORD not in caplog.text
    assert "wrong-pass-1" not in caplog.text
    assert token not in caplog.text
