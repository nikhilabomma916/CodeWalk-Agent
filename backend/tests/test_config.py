from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Environment, Settings
from tests.conftest import FRONTEND_ORIGIN, build_app, make_settings

STRONG_KEY = "k" * 48


def test_environment_variables_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEWALK_ENV", "production")
    monkeypatch.setenv("CODEWALK_PORT", "9123")
    monkeypatch.setenv("CODEWALK_CORS_ORIGINS", "https://app.example.com, https://admin.example.com/")
    monkeypatch.setenv("CODEWALK_SECRET_KEY", STRONG_KEY)
    monkeypatch.setenv("CODEWALK_LOG_LEVEL", "debug")

    settings = Settings(_env_file=None)

    assert settings.env is Environment.PRODUCTION
    assert settings.port == 9123
    assert settings.cors_origins == ["https://app.example.com", "https://admin.example.com"]
    assert settings.log_level == "DEBUG"


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        make_settings(cors_origins=["*"])


def test_cors_origin_requires_scheme() -> None:
    with pytest.raises(ValidationError, match="http"):
        make_settings(cors_origins=["localhost:3000"])


@pytest.mark.parametrize("key", ["", "change-me", "short"])
def test_production_requires_strong_secret_key(key: str) -> None:
    with pytest.raises(ValidationError, match="CODEWALK_SECRET_KEY"):
        make_settings(env="production", secret_key=key)


def test_blank_optional_values_become_none() -> None:
    settings = make_settings(ai_provider="  ", ai_api_key="", database_url="")
    assert settings.ai_provider is None
    assert settings.ai_api_key is None
    assert settings.database_url is None


def test_secrets_are_masked_in_repr() -> None:
    settings = make_settings(
        secret_key=STRONG_KEY,
        ai_api_key="sk-live-abcdef",
        database_url="postgresql://user:pw@localhost/db",
    )
    rendered = repr(settings)
    assert STRONG_KEY not in rendered
    assert "sk-live-abcdef" not in rendered
    assert "user:pw" not in rendered


def test_docs_enabled_outside_production(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/info" in schema["paths"]


def test_docs_disabled_in_production() -> None:
    app = build_app(env="production", secret_key=STRONG_KEY, cors_origins=["https://app.example.com"])
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/api/v1/openapi.json").status_code == 404
        info = client.get("/api/v1/info").json()
        assert info["docs_url"] is None


def test_info_exposes_no_secrets() -> None:
    app = build_app(secret_key=STRONG_KEY, ai_api_key="sk-live-abcdef")
    with TestClient(app) as client:
        response = client.get("/api/v1/info")
    assert response.status_code == 200
    assert set(response.json()) == {"name", "version", "api_version", "environment", "docs_url"}
    assert STRONG_KEY not in response.text
    assert "sk-live" not in response.text


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers

    simple = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_root_points_to_api(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["api"] == "/api/v1"


def test_production_requires_https_origins_and_secure_cookies() -> None:
    """Development defaults must not silently become production settings."""
    with pytest.raises(ValidationError, match="https://"):
        make_settings(env="production", secret_key=STRONG_KEY, cors_origins=["http://localhost:3000"])
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        make_settings(
            env="production",
            secret_key=STRONG_KEY,
            cors_origins=["https://app.example.com"],
            session_cookie_secure=False,
        )
    production = make_settings(
        env="production", secret_key=STRONG_KEY, cors_origins=["https://app.example.com"]
    )
    assert production.cookie_secure is True
    assert production.docs_are_enabled is False


def test_security_headers_on_api_and_docs() -> None:
    with TestClient(build_app()) as client:
        api = client.get("/api/v1/health")
        assert api.headers["X-Content-Type-Options"] == "nosniff"
        assert api.headers["X-Frame-Options"] == "DENY"
        assert api.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert api.headers["Cache-Control"] == "no-store"
        assert "Strict-Transport-Security" not in api.headers  # never over plain HTTP in development
        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "Content-Security-Policy" not in docs.headers  # Swagger UI loads its own scripts
    production = build_app(env="production", secret_key=STRONG_KEY, cors_origins=["https://app.example.com"])
    with TestClient(production) as client:
        assert client.get("/api/v1/health").headers["Strict-Transport-Security"].startswith("max-age=")
