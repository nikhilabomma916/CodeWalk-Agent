"""Hosting behavior: Vercel origins and port, bounded shutdown, and the TypeScript worker's cleanup.

Nothing here imitates Vercel: the Vercel settings are plain environment variables, and the shutdown
tests run the real worker and (on POSIX) the real server process with a real SIGTERM.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.__main__ as launcher
from app.core.config import VERCEL_MAX_REQUEST_BODY_BYTES, Settings
from app.services.analysis.analyzers.base import MAX_DIAGNOSTICS
from app.services.analysis.engine import AnalysisEngine, SourceTooLargeError
from app.services.analysis.typescript_worker import TypeScriptWorker, TypeScriptWorkerError
from tests.conftest import FRONTEND_ORIGIN, build_app, make_settings

STRONG_KEY = "k" * 48
BACKEND_DIR = Path(__file__).resolve().parents[1]


# --- Vercel deployment URLs as allowed origins -------------------------------------------------


def test_vercel_deployment_urls_are_allowed_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_URL", "codewalk-abc123-team.vercel.app")
    monkeypatch.setenv("VERCEL_BRANCH_URL", "codewalk-git-feature-team.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "codewalk.example.com")
    monkeypatch.setenv("CODEWALK_CORS_ORIGINS", "https://codewalk.example.com")

    settings = Settings(_env_file=None)

    assert settings.on_vercel
    assert settings.allowed_origins == [
        "https://codewalk.example.com",  # listed once, although it is also the production URL
        "https://codewalk-abc123-team.vercel.app",
        "https://codewalk-git-feature-team.vercel.app",
    ]
    assert settings.cors_origins == ["https://codewalk.example.com"]


def test_vercel_urls_are_ignored_outside_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("VERCEL_URL", "somewhere.vercel.app")
    settings = Settings(_env_file=None)
    assert not settings.on_vercel
    assert "https://somewhere.vercel.app" not in settings.allowed_origins


@pytest.mark.parametrize(
    "value", ["https://x.vercel.app", "x.vercel.app/path", "localhost", "*.vercel.app", "a b.vercel.app"]
)
def test_vercel_urls_must_be_host_names(value: str) -> None:
    with pytest.raises(ValidationError, match="host names"):
        make_settings(vercel="1", vercel_url=value)


def test_production_on_vercel_accepts_its_own_url_and_nothing_else() -> None:
    """No CODEWALK_CORS_ORIGINS needed for the deployment itself; other origins are still refused."""
    application = build_app(
        env="production",
        secret_key=STRONG_KEY,
        cors_origins=[],
        vercel="1",
        vercel_url="codewalk-abc123-team.vercel.app",
    )
    # The backend may see plain http behind the platform's proxy; the origin check must not depend on it.
    with TestClient(application, base_url="http://internal-backend") as client:
        own = client.post(
            "/api/v1/auth/login", json={}, headers={"Origin": "https://codewalk-abc123-team.vercel.app"}
        )
        assert own.status_code != 403
        foreign = client.post("/api/v1/auth/login", json={}, headers={"Origin": "https://evil.example"})
        assert foreign.status_code == 403
        assert foreign.json()["error"]["code"] == "origin_not_allowed"
        preflight = client.options(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in preflight.headers


def test_vercel_does_not_relax_production_rules() -> None:
    with pytest.raises(ValidationError, match="https://"):
        make_settings(
            env="production",
            secret_key=STRONG_KEY,
            cors_origins=["http://codewalk.example.com"],
            vercel="1",
            vercel_url="codewalk.vercel.app",
        )
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        make_settings(
            env="production",
            secret_key=STRONG_KEY,
            cors_origins=[],
            vercel="1",
            session_cookie_secure=False,
        )


# --- /api routing ------------------------------------------------------------------------------


def test_every_api_route_is_under_the_api_prefix_that_vercel_routes_to_the_backend() -> None:
    """vercel.json sends /api/(.*) to the backend unchanged; everything else goes to the frontend."""
    application = build_app(docs_enabled=False)  # as in production
    paths = list(application.openapi()["paths"])
    assert paths
    assert all(path.startswith("/api/v1/") for path in paths), [
        p for p in paths if not p.startswith("/api/v1/")
    ]
    with TestClient(application) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        assert client.get("/api/api/v1/health/live").status_code == 404  # no doubled prefix
        assert client.get("/docs").status_code == 404
        # Outside /api only "/" and "/metrics" exist; on Vercel those paths reach the frontend instead.
        assert client.get("/").status_code == 200


# --- Request body limit on Vercel ----------------------------------------------------------------


def test_request_body_limit_is_unchanged_outside_vercel() -> None:
    assert make_settings().request_body_limit == 6 * 1024 * 1024
    assert (
        make_settings(max_request_body_bytes=8_000_000, max_source_bytes=1000).request_body_limit == 8_000_000
    )


def test_request_body_limit_is_capped_at_vercels_limit() -> None:
    assert make_settings(vercel="1").request_body_limit == VERCEL_MAX_REQUEST_BODY_BYTES
    # A smaller configured limit is kept.
    assert make_settings(vercel="1", max_request_body_bytes=1_000_000).request_body_limit == 1_000_000


def test_vercel_limit_must_still_exceed_the_source_limit() -> None:
    with pytest.raises(ValidationError, match="on Vercel it is at most 4500000 bytes"):
        make_settings(vercel="1", max_source_bytes=VERCEL_MAX_REQUEST_BODY_BYTES)


def test_api_on_vercel_answers_oversized_bodies_with_its_own_413() -> None:
    application = build_app(vercel="1", vercel_url="codewalk-abc123-team.vercel.app")
    headers = {"Content-Type": "application/json"}
    with TestClient(application) as client:
        at_limit = client.post(
            "/api/v1/auth/login", content=b" " * VERCEL_MAX_REQUEST_BODY_BYTES, headers=headers
        )
        assert at_limit.status_code == 422  # read and parsed: empty JSON, not a size error
        over = client.post(
            "/api/v1/auth/login", content=b" " * (VERCEL_MAX_REQUEST_BODY_BYTES + 1), headers=headers
        )
        assert over.status_code == 413
        assert over.json()["error"]["code"] == "payload_too_large"

        def chunks() -> Any:
            for _ in range(5):
                yield b" " * 1_000_000

        streamed = client.post("/api/v1/auth/login", content=chunks(), headers=headers)
        assert streamed.status_code == 413
        assert streamed.json()["error"]["code"] == "payload_too_large"


# --- Listening port and graceful shutdown settings ----------------------------------------------


def test_listen_port_uses_codewalk_port_outside_vercel() -> None:
    settings = make_settings(port=9123)
    assert launcher.listen_port(settings, {"PORT": "3000"}) == 9123


def test_listen_port_uses_vercel_port_in_a_vercel_container() -> None:
    settings = make_settings(port=9123, vercel="1")
    assert launcher.listen_port(settings, {"PORT": "8000"}) == 8000
    assert launcher.listen_port(settings, {}) == 80  # Vercel's default when PORT is not set


def test_server_shuts_down_within_the_configured_grace_period(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(launcher, "get_settings", lambda: make_settings(shutdown_timeout_seconds=12))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    launcher.main()
    assert captured["timeout_graceful_shutdown"] == 12
    assert captured["port"] == 8000
    assert make_settings().shutdown_timeout_seconds < 30  # below Vercel's and Compose's grace period


def test_lifespan_shutdown_closes_the_typescript_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    monkeypatch.setattr(TypeScriptWorker, "close", lambda self, timeout=5.0: closed.append(True))
    with TestClient(build_app()):
        assert closed == []
    assert closed == [True]


# --- The TypeScript worker process --------------------------------------------------------------


@pytest.fixture
def worker() -> Any:
    worker = TypeScriptWorker()
    reason = worker.unavailable_reason()
    if reason:
        pytest.skip(f"TypeScript analyzer unavailable: {reason}")
    yield worker
    worker.close()


def test_close_ends_the_worker_cleanly(worker: TypeScriptWorker) -> None:
    worker.analyze("a.ts", "export const a: number = 1;", timeout=30)
    process = worker._process
    assert process is not None
    assert process.poll() is None

    started = time.monotonic()
    worker.close()

    assert time.monotonic() - started < 5
    assert process.poll() == 0  # exited on end of input, not killed
    assert worker._process is None


def test_close_does_not_wait_for_a_request_in_progress(worker: TypeScriptWorker) -> None:
    worker.analyze("a.ts", "export {};", timeout=30)
    process = worker._process
    assert process is not None
    errors: list[Exception] = []

    def slow_request() -> None:
        # A large file keeps the worker busy; the request may also finish before close() lands.
        source = "\n".join(f"export const v{i}: number = {i};" for i in range(40_000))
        try:
            worker.analyze("big.ts", source, timeout=60)
        except TypeScriptWorkerError as exc:
            errors.append(exc)

    thread = threading.Thread(target=slow_request)
    thread.start()
    time.sleep(0.2)
    started = time.monotonic()
    worker.close(timeout=3)
    thread.join(timeout=10)

    assert time.monotonic() - started < 5
    assert not thread.is_alive()
    assert process.poll() is not None
    assert all("stopped" in str(e) or "shuts down" in str(e) for e in errors)


def test_no_worker_is_started_after_close(worker: TypeScriptWorker) -> None:
    worker.close()
    with pytest.raises(TypeScriptWorkerError, match="shuts down"):
        worker.analyze("a.ts", "export {};", timeout=30)
    assert worker._process is None


def test_worker_exits_when_its_parent_goes_away(worker: TypeScriptWorker) -> None:
    """If the server is killed outright, the worker's stdin closes and it ends by itself."""
    worker.analyze("a.ts", "export {};", timeout=30)
    process = worker._process
    assert process is not None
    assert process.stdin is not None
    process.stdin.close()  # what the operating system does when the parent process dies
    assert process.wait(timeout=5) == 0


# --- Bounded work per TypeScript request ---------------------------------------------------------
# The worker has no batches: each request is one file. What bounds its memory and CPU on a small
# hosting instance is the source limit (checked before the worker is called), the per-request
# timeout, the Node heap cap (--max-old-space-size=512), and one request at a time per instance.
# Responses carry at most MAX_DIAGNOSTICS findings; the total is always reported.


def _type_errors(count: int) -> str:
    return "\n".join(f'export const v{i}: number = "text";' for i in range(count))


def test_worker_returns_every_diagnostic_of_a_file(worker: TypeScriptWorker) -> None:
    assert worker.analyze("ok.ts", "export const a: number = 1;\n", timeout=30) == []
    items = worker.analyze("many.ts", _type_errors(1200), timeout=60)
    assert len(items) == 1200
    assert sorted(item["start"]["line"] for item in items) == list(range(1, 1201))


def test_api_results_are_capped_but_report_the_total(worker: TypeScriptWorker) -> None:
    engine = AnalysisEngine.create_default(
        max_source_bytes=2 * 1024 * 1024, timeout_seconds=60, typescript_worker=worker
    )
    result = engine.analyze(_type_errors(MAX_DIAGNOSTICS + 100), file_path="many.ts")
    assert len(result.diagnostics) == MAX_DIAGNOSTICS
    assert result.metadata["truncated"] is True
    assert result.metadata["total_diagnostics"] == MAX_DIAGNOSTICS + 100
    assert [d.line for d in result.diagnostics] == list(range(1, MAX_DIAGNOSTICS + 1))  # first ones, in order


def test_oversized_source_never_reaches_the_worker() -> None:
    class CountingWorker(TypeScriptWorker):
        calls = 0

        def analyze(self, file_name: str, text: str, timeout: float) -> list[dict[str, Any]]:
            CountingWorker.calls += 1
            return []

    engine = AnalysisEngine.create_default(
        max_source_bytes=1000, timeout_seconds=5, typescript_worker=CountingWorker()
    )
    with pytest.raises(SourceTooLargeError):
        engine.analyze("x" * 1001, file_path="big.ts")
    engine.analyze("export {};", file_path="small.ts")
    assert CountingWorker.calls == 1


def test_concurrent_requests_are_serialized_without_mixing_results(worker: TypeScriptWorker) -> None:
    results: dict[int, list[dict[str, Any]]] = {}

    def run(count: int) -> None:
        results[count] = worker.analyze(f"f{count}.ts", _type_errors(count), timeout=60)

    threads = [threading.Thread(target=run, args=(count,)) for count in (1, 5, 20, 50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert {count: len(items) for count, items in results.items()} == {1: 1, 5: 5, 20: 20, 50: 50}


# --- The real server process and SIGTERM (POSIX) ------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _children(pid: int) -> set[int]:
    children: set[int] = set()
    for task in Path(f"/proc/{pid}/task").glob("*"):
        text = (task / "children").read_text() if (task / "children").exists() else ""
        children.update(int(child) for child in text.split())
    return children


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"  # a zombie has already exited


@pytest.mark.skipif(not Path("/proc/self/task").is_dir(), reason="needs Linux /proc to see child processes")
def test_sigterm_stops_the_server_and_its_typescript_worker(tmp_path: Path) -> None:
    port = _free_port()
    env = {
        **os.environ,
        "CODEWALK_ENV": "testing",
        "CODEWALK_HOST": "127.0.0.1",
        "CODEWALK_PORT": str(port),
        "CODEWALK_DATABASE_URL": "",
        "CODEWALK_AI_ENABLED": "false",
        "RAG_ENABLED": "false",
        "CODEWALK_LOG_LEVEL": "INFO",
        "CODEWALK_LOG_FORMAT": "text",
        "CODEWALK_SHUTDOWN_TIMEOUT_SECONDS": "5",
    }
    log_path = tmp_path / "server.log"
    log = log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "app"], cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=2):
                    break
            except OSError:
                if time.monotonic() > deadline or server.poll() is not None:
                    pytest.fail("the server did not start")
                time.sleep(0.2)
        # The background warm-up starts the TypeScript worker when Node and the analyzer are installed.
        node_children: set[int] = set()
        if TypeScriptWorker().unavailable_reason() is None:
            deadline = time.monotonic() + 30
            while not node_children and time.monotonic() < deadline:
                node_children = _children(server.pid)
                time.sleep(0.2)
            assert node_children, "the TypeScript worker did not start"

        started = time.monotonic()
        server.send_signal(signal.SIGTERM)
        # uvicorn (>= 0.29) finishes its graceful shutdown, restores the default handler and then
        # re-raises SIGTERM, so a clean exit is 0 or "terminated by SIGTERM"; the log proves which.
        assert server.wait(timeout=25) in (0, -signal.SIGTERM)
        assert time.monotonic() - started < 15

        log.flush()
        output = log_path.read_text(encoding="utf-8")
        assert "Shutting down" in output, output[-2000:]  # the lifespan shutdown ran (worker, pool)
        assert "Application shutdown complete" in output, output[-2000:]  # ...and finished
        assert "Traceback" not in output, output[-2000:]
        deadline = time.monotonic() + 5
        while any(_alive(child) for child in node_children) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not any(_alive(child) for child in node_children), "the worker outlived the server"
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)
        log.close()


def test_frontend_origin_still_allowed_in_development() -> None:
    assert make_settings().allowed_origins == [FRONTEND_ORIGIN]
