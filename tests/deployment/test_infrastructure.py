"""Infrastructure security tests (Module 15).

These inspect the real, resolved configuration rather than searching for strings:
``docker compose config --format json`` for the compose files, the Dockerfiles' final stages,
the built images (``docker image inspect`` and files inside them), and nginx's own parser.

    npm run test:infra       # needs Docker; build the images first for the image checks

Image checks skip (with the reason) when the images have not been built; CI builds them first.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import uuid
from functools import cache
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "docker-compose.prod.yml"
DEV = ROOT / "docker-compose.yml"
TAG = "local"
IMAGES = {
    "backend": f"codewalk-backend:{TAG}",
    "frontend": f"codewalk-frontend:{TAG}",
    "proxy": f"codewalk-proxy:{TAG}",
}
LONG_RUNNING = {"db", "backend", "frontend", "proxy"}
APP_SERVICES = {"migrate", "backend", "frontend", "proxy"}
SECRET_NAME = re.compile(r"(PASSWORD|SECRET|API_KEY|PRIVATE_KEY|(^|_)TOKEN$)", re.IGNORECASE)

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI not available")


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    full_env = {**os.environ, **(env or {})}
    return subprocess.run(args, capture_output=True, text=True, check=False, env=full_env, cwd=ROOT)  # noqa: S603


def _placeholder_env() -> dict[str, str]:
    # Random throwaway values: config rendering needs them; they are never printed.
    return {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "CODEWALK_SECRET_KEY": secrets.token_urlsafe(48),
        "ANTHROPIC_API_KEY": "",
        "VOYAGE_API_KEY": "",
    }


@cache
def prod_config() -> dict[str, Any]:
    result = _run(
        "docker", "compose", "-f", str(PROD), "--env-file", str(ROOT / ".env.production.example"),
        "config", "--format", "json", env=_placeholder_env(),
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


@cache
def dev_config() -> dict[str, Any]:
    result = _run(
        "docker", "compose", "-f", str(DEV), "--profile", "app", "config", "--format", "json",
        env={"POSTGRES_PASSWORD": secrets.token_urlsafe(24)},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def _image_exists(image: str) -> bool:
    return _run("docker", "image", "inspect", image).returncode == 0


def _require_image(image: str) -> None:
    if not _image_exists(image):
        pytest.skip(f"{image} is not built (docker compose -f docker-compose.prod.yml build)")


# --- Production compose ------------------------------------------------------------------------


def test_only_the_proxy_is_published() -> None:
    services = prod_config()["services"]
    published = {name for name, svc in services.items() if svc.get("ports")}
    assert published == {"proxy"}
    assert {p["target"] for p in services["proxy"]["ports"]} == {8080, 8443}


def test_database_is_isolated_on_an_internal_network() -> None:
    config = prod_config()
    assert config["networks"]["data"].get("internal") is True
    services = config["services"]
    assert set(services["db"]["networks"]) == {"data"}
    assert "ports" not in services["db"]
    # The browser-facing tier cannot reach the database at all.
    assert "data" not in services["frontend"]["networks"]
    assert "data" not in services["proxy"]["networks"]


def test_health_checks_and_restart_policies() -> None:
    services = prod_config()["services"]
    for name in LONG_RUNNING:
        assert services[name].get("healthcheck", {}).get("test"), f"{name} has no health check"
        assert services[name].get("restart") in {"unless-stopped", "always"}, name
    assert services["migrate"]["restart"] == "no"  # a failed migration must not loop


def test_startup_order_waits_for_database_and_migrations() -> None:
    services = prod_config()["services"]
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["backend"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["proxy"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]


def test_no_source_mounts_and_no_development_commands() -> None:
    services = prod_config()["services"]
    for name, svc in services.items():
        for mount in svc.get("volumes", []):
            if mount["type"] == "bind":
                # Only the proxy's certificates and ACME webroot come from the host, read-only.
                assert name == "proxy", f"{name} bind-mounts {mount['source']}"
                assert mount["target"] in {"/etc/nginx/tls", "/var/www/acme"}
                assert mount.get("read_only") is True
        command = " ".join(svc.get("command") or [])
        assert not re.search(r"--reload|npm run dev|next dev|uvicorn.*--reload", command), name
    assert services["backend"]["environment"]["CODEWALK_ENV"] == "production"


def test_application_containers_are_hardened() -> None:
    services = prod_config()["services"]
    for name in APP_SERVICES:
        svc = services[name]
        assert svc.get("read_only") is True, name
        assert svc.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name


def test_required_secrets_fail_fast_and_ai_keys_stay_optional() -> None:
    env = _placeholder_env()
    for required in ("POSTGRES_PASSWORD", "CODEWALK_SECRET_KEY"):
        missing = {**env, required: ""}
        result = _run(
            "docker", "compose", "-f", str(PROD), "--env-file", str(ROOT / ".env.production.example"),
            "config", "-q", env={**missing, "POSTGRES_PASSWORD": missing["POSTGRES_PASSWORD"] or ""},
        )  # fmt: skip
        assert result.returncode != 0, f"compose accepted an empty {required}"
        assert required in result.stderr
    backend = prod_config()["services"]["backend"]["environment"]
    assert backend["ANTHROPIC_API_KEY"] == ""  # optional: absent keys render as empty
    assert backend["VOYAGE_API_KEY"] == ""


def test_every_compose_variable_is_documented() -> None:
    used = set(re.findall(r"\$\{([A-Z0-9_]+)", PROD.read_text(encoding="utf-8")))
    documented = set(
        re.findall(r"^([A-Z0-9_]+)=", (ROOT / ".env.production.example").read_text(encoding="utf-8"), re.M)
    )
    assert used - documented == set()


def test_example_files_hold_placeholders_only() -> None:
    for name in (".env.example", ".env.production.example"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if match and SECRET_NAME.search(match.group(1)):
                value = match.group(2).strip()
                assert value in {"", "replace-me", "replace-with-random-secret"}, f"{name}: {match.group(1)}"


def test_dev_compose_keeps_services_on_localhost() -> None:
    services = dev_config()["services"]
    for name, svc in services.items():
        for port in svc.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1", f"{name} publishes on {port.get('host_ip')}"
    # The database service and volume are unchanged, so existing development data is kept.
    assert services["postgres"]["volumes"][0]["source"] == "postgres-data"


# --- Dockerfiles and images ----------------------------------------------------------------------


def _final_stage(dockerfile: Path) -> list[str]:
    lines = [line.strip() for line in dockerfile.read_text(encoding="utf-8").splitlines()]
    starts = [i for i, line in enumerate(lines) if line.upper().startswith("FROM ")]
    return [line for line in lines[starts[-1] :] if line and not line.startswith("#")]


@pytest.mark.parametrize(
    "dockerfile",
    ["backend/Dockerfile", "backend/Dockerfile.vercel", "frontend/Dockerfile", "deploy/nginx/Dockerfile"],
)
def test_dockerfiles_bake_in_no_secrets(dockerfile: str) -> None:
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    for match in re.finditer(r"^\s*(ARG|ENV)\s+(.+)$", text, re.M):
        for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", match.group(2)) or [
            match.group(2).split("=")[0]
        ]:
            assert not SECRET_NAME.search(name), f"{dockerfile}: {match.group(1)} {name}"
    assert not re.search(r"COPY[^\n]*\.env", text)


@pytest.mark.parametrize(
    "dockerfile", ["backend/Dockerfile", "backend/Dockerfile.vercel", "frontend/Dockerfile"]
)
def test_final_stage_runs_as_non_root(dockerfile: str) -> None:
    users = [line.split()[1] for line in _final_stage(ROOT / dockerfile) if line.upper().startswith("USER ")]
    assert users, f"{dockerfile} final stage sets no USER"
    assert users[-1].split(":")[0] not in {"root", "0"}


@pytest.mark.parametrize("service", sorted(IMAGES))
def test_images_run_as_non_root(service: str) -> None:
    image = IMAGES[service]
    _require_image(image)
    user = _run("docker", "image", "inspect", image, "--format", "{{.Config.User}}").stdout.strip()
    assert user, f"{image} sets no user"
    assert user.split(":")[0] not in {"root", "0"}, f"{image} runs as {user!r}"
    uid = _run("docker", "run", "--rm", "--entrypoint", "id", image, "-u").stdout.strip()
    assert uid, f"{image}: no uid"
    assert uid != "0", f"{image} runs as uid {uid}"


@pytest.mark.parametrize("service", sorted(IMAGES))
def test_images_contain_no_env_or_key_files(service: str) -> None:
    image = IMAGES[service]
    _require_image(image)
    found = _run(
        "docker", "run", "--rm", "--entrypoint", "find", image, "/app", "/etc/nginx", "-xdev",
        "(", "-name", ".env", "-o", "-name", ".env.*", "-o", "-name", "*.pem", "-o", "-name", "*.key", ")",
        "-not", "-name", ".env.example",
    )  # fmt: skip
    assert found.stdout.strip() == "", f"{image}: {found.stdout.strip()}"


def test_frontend_bundle_has_no_backend_secrets() -> None:
    """No provider key names, key-shaped values or credentialed connection strings reach the
    browser. (Setting names in help text, such as CODEWALK_DATABASE_URL, are not secrets.)"""
    image = IMAGES["frontend"]
    _require_image(image)
    pattern = (
        r"ANTHROPIC_API_KEY|VOYAGE_API_KEY|CODEWALK_AI_API_KEY|CODEWALK_SECRET_KEY|POSTGRES_PASSWORD"
        r"|sk-ant-[A-Za-z0-9_-]{8,}|postgres(ql)?(+psycopg)?://[^:/s\"]+:[^@s\"]+@"
    )
    found = _run(
        "docker", "run", "--rm", "--entrypoint", "grep", image, "-rlE", pattern, "/app/.next", "/app/public"
    )
    assert found.returncode == 1, f"backend secrets in the frontend image: {found.stdout.strip()}"


def test_backend_image_has_no_development_tools() -> None:
    image = IMAGES["backend"]
    _require_image(image)
    found = _run("docker", "run", "--rm", "--entrypoint", "ls", image, "/opt/venv/bin")
    tools = set(found.stdout.split())
    assert {"uvicorn", "alembic", "ruff"} <= tools  # runtime needs (ruff is a Python analyzer)
    assert not tools & {"pytest", "mypy"}


def test_proxy_configuration_parses_in_both_modes() -> None:
    image = IMAGES["proxy"]
    _require_image(image)
    hosts = ["--add-host", "backend:127.0.0.1", "--add-host", "frontend:127.0.0.1"]
    test = "/docker-entrypoint.d/40-codewalk-site.sh && nginx -t"
    plain = _run("docker", "run", "--rm", *hosts, "--entrypoint", "sh", image, "-c", test)
    assert plain.returncode == 0, plain.stderr
    # HTTPS mode needs a certificate to parse: a throwaway one, created in a disposable volume only
    # for this syntax check (never stored on the host or used to serve traffic).
    volume = f"codewalk-nginx-test-{uuid.uuid4().hex[:8]}"
    try:
        generate = _run(
            "docker", "run", "--rm", "-v", f"{volume}:/tls", "python:3.12-slim-bookworm", "sh", "-c",
            "openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost "
            "-keyout /tls/privkey.pem -out /tls/fullchain.pem 2>/dev/null && chmod 644 /tls/*.pem",
        )  # fmt: skip
        assert generate.returncode == 0, generate.stderr
        tls = _run(
            "docker", "run", "--rm", *hosts, "-e", "CODEWALK_PROXY_TLS=on",
            "-v", f"{volume}:/etc/nginx/tls:ro",
            "--entrypoint", "sh", image, "-c", test,
        )  # fmt: skip
        assert tls.returncode == 0, tls.stderr
        assert "TLS on" in tls.stdout
    finally:
        _run("docker", "volume", "rm", "-f", volume)
    missing = _run("docker", "run", "--rm", "-e", "CODEWALK_PROXY_TLS=on", image)
    assert missing.returncode != 0  # refuses to start without certificates


# --- Repository ------------------------------------------------------------------------------------


def test_no_secret_files_are_tracked() -> None:
    tracked = _run("git", "ls-files").stdout.splitlines()
    forbidden = re.compile(r"(^|/)\.env($|\.(?!example$|production\.example$))|\.(pem|key|crt|p12|pfx|dump)$")
    assert [path for path in tracked if forbidden.search(path)] == []
