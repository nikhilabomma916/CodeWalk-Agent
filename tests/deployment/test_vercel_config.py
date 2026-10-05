"""Vercel configuration (vercel.json and backend/Dockerfile.vercel), checked without Vercel or Docker.

Vercel routes a request to the first service whose top-level rewrite matches and the service sees
the original path (vercel.com/docs/services/routing), so the backend receives /api/v1/... exactly
as FastAPI serves it. What only a real deployment can confirm is listed in docs/deployment/vercel.md.

    npm run test:infra
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "vercel.json"


def _config() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    return value


def _route(path: str) -> str:
    """The service Vercel picks for ``path``: the first rewrite whose source matches."""
    for rule in _config()["rewrites"]:
        if re.fullmatch(rule["source"], path):
            service: str = rule["destination"]["service"]
            return service
    raise AssertionError(f"no rewrite matches {path}")


def test_services_point_at_the_existing_apps() -> None:
    services = _config()["services"]
    assert set(services) == {"frontend", "backend"}
    assert (ROOT / services["frontend"]["root"] / "next.config.ts").is_file()
    backend_root = ROOT / services["backend"]["root"]
    assert (backend_root / "app" / "main.py").is_file()
    assert (backend_root / services["backend"]["entrypoint"]).is_file()


@pytest.mark.parametrize(
    ("path", "service"),
    [
        ("/api/v1/health/live", "backend"),
        ("/api/v1/health/ready", "backend"),
        ("/api/v1/auth/login", "backend"),
        ("/api/v1/projects/0b6f/files/import", "backend"),
        ("/api/v1/agent/runs", "backend"),
        ("/", "frontend"),
        ("/app/projects", "frontend"),
        ("/login", "frontend"),
        ("/healthz", "frontend"),
        ("/_next/static/chunks/app.js", "frontend"),
        ("/monaco/vs/loader.js", "frontend"),
        ("/apidocs", "frontend"),  # only the /api/ prefix goes to the backend
        ("/metrics", "frontend"),  # the backend's metrics endpoint is not public on Vercel
    ],
)
def test_rewrites_send_only_api_paths_to_the_backend(path: str, service: str) -> None:
    assert _route(path) == service


def test_no_rewrite_changes_the_path_the_backend_sees() -> None:
    """A destination ``path`` would only pick a route, and no second /api prefix is added."""
    for rule in _config()["rewrites"]:
        assert set(rule["destination"]) == {"service"}
    for service in _config()["services"].values():
        assert "rewrites" not in service
        assert "routes" not in service


def _significant(dockerfile: Path) -> list[str]:
    """Build instructions (stages, dependencies, files, user, command), comments and blank lines dropped."""
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    keep = ("ARG", "FROM", "WORKDIR", "COPY", "RUN", "USER", "CMD")
    return [line.strip() for line in text.splitlines() if line.strip().split(" ", 1)[0] in keep]


def test_vercel_image_builds_the_same_application_as_the_production_image() -> None:
    assert _significant(ROOT / "backend" / "Dockerfile.vercel") == _significant(
        ROOT / "backend" / "Dockerfile"
    )


def test_vercel_image_only_adds_the_documented_environment() -> None:
    text = (ROOT / "backend" / "Dockerfile.vercel").read_text(encoding="utf-8")
    env = dict(re.findall(r"^\s*([A-Z_]+)=(\S+?)\s*\\?$", text.split("USER ")[0].split("ENV PATH")[1], re.M))
    assert env == {
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CODEWALK_ENV": "production",
        "CODEWALK_HOST": "0.0.0.0",  # noqa: S104 - the container's only listener, behind Vercel
        "CODEWALK_PORT": "8000",
        "CODEWALK_NODE_BINARY": "/usr/local/bin/node",
        "CODEWALK_CORS_ORIGINS": '""',  # the VERCEL_* URLs only, unless the project sets a domain
        "FORWARDED_ALLOW_IPS": "*",
    }
    assert not re.search(r"^HEALTHCHECK", text, re.M)
