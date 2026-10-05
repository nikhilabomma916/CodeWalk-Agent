"""Module 22: production preflight, database pooler settings, and documented configuration."""

from __future__ import annotations

import os
from typing import Any

import pytest

import app.db.session as session_module
from app import preflight
from app.core.config import Settings
from app.db.session import Database
from tests.conftest import make_settings

SECRET_KEY = "s" * 48
CLIENT_SECRET = "github-client-secret-value"
# Set by the hosting platform, or internal.
UNDOCUMENTED = {
    "CODEWALK_APP_NAME",
    "VERCEL",
    "VERCEL_URL",
    "VERCEL_BRANCH_URL",
    "VERCEL_PROJECT_PRODUCTION_URL",
}


def production(**extra: Any) -> Settings:
    return make_settings(env="production", secret_key=SECRET_KEY, cors_origins=[], **extra)


def statuses(checks: list[preflight.Check]) -> dict[str, str]:
    return {check.name: check.status for check in checks}


def test_a_minimal_production_configuration_passes() -> None:
    checks = preflight.configuration_checks(production(database_url="postgresql+psycopg://u:p@db/x"))
    assert statuses(checks) == {
        "environment": "PASS",
        "database_url": "PASS",
        "session_cookie": "PASS",
        "allowed_origins": "PASS",
        "ai_provider": "PASS",
        "rag_provider": "PASS",
        "github": "PASS",
    }


def test_missing_database_and_misconfigured_integrations_fail() -> None:
    checks = statuses(
        preflight.configuration_checks(
            production(
                ai_enabled=True,
                ai_provider="gemini",
                github_client_id="Iv1.x",
                github_client_secret=CLIENT_SECRET,
            )
        )
    )
    assert checks["database_url"] == "FAIL"
    assert checks["ai_provider"] == "FAIL"  # no GEMINI_API_KEY and no model
    assert checks["github"] == "FAIL"  # partly configured


def test_ollama_in_production_is_flagged() -> None:
    checks = statuses(
        preflight.configuration_checks(
            production(ai_enabled=True, ai_provider="ollama", OLLAMA_MODEL="llama3.1:8b")
        )
    )
    assert checks["ai_provider"] == "PASS"
    assert checks["ai_ollama"] == "WARN"


def test_preflight_reports_invalid_settings_without_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in list(os.environ):
        if name.startswith("CODEWALK_") or name.endswith("_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    monkeypatch.setenv("CODEWALK_ENV", "production")
    monkeypatch.setenv("CODEWALK_SECRET_KEY", "short-secret-value")
    monkeypatch.setenv("CODEWALK_GITHUB_CLIENT_SECRET", CLIENT_SECRET)
    assert preflight.main(["--no-db"]) == 1
    output = capsys.readouterr()
    assert "FAIL" in output.out
    assert "CODEWALK_SECRET_KEY" in output.out
    assert "short-secret-value" not in output.out + output.err
    assert CLIENT_SECRET not in output.out + output.err


def test_preflight_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(preflight, "run", lambda **_: [preflight.Check("database", "PASS", "connected")])
    assert preflight.main(["--json", "--no-db"]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out


@pytest.mark.parametrize("enabled", [True, False])
def test_prepared_statements_can_be_disabled_for_poolers(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_engine(url: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(session_module, "create_engine", fake_engine)
    with pytest.raises(RuntimeError):
        Database.from_settings(
            make_settings(database_url="postgresql+psycopg://u:p@db/x", database_prepared_statements=enabled)
        )
    connect_args = captured["connect_args"]
    if enabled:
        assert "prepare_threshold" not in connect_args
    else:
        assert connect_args["prepare_threshold"] is None  # psycopg: never prepare
