"""Module 14 performance measurements. Prints measured numbers; nothing is estimated.

Part A (live HTTP) runs against a running backend, including its real database:
project upload, project scan (intelligence), search, context, deterministic analysis
(normal, large, oversized), and concurrent search throughput, for several project sizes.

Part B (in-process, optional) uses the test-only stub embedder and stub model against a
dedicated *_test database to measure CodeWalk's own overhead for semantic indexing,
pgvector retrieval, and agent orchestration, without any provider network time, and
counts SQL statements per request. Its numbers exclude real provider latency by design.

Usage (from the repository root):
  uv --directory backend run python ../scripts/performance.py --api http://127.0.0.1:8000/api/v1
  # plus Part B (needs a reachable *_test database):
  CODEWALK_TEST_DATABASE_URL=postgresql+psycopg://...codewalk_test \\
    uv --directory backend run python ../scripts/performance.py --api ... --in-process
"""

# ruff: noqa: B023  (every timed lambda runs immediately, inside its loop iteration)

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from tests.fixtures import projects as fx  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
PASSWORD = "perf-check-Pass-7"


def ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))]
    return {
        "n": len(samples),
        "p50_ms": ms(statistics.median(ordered)),
        "p95_ms": ms(p95),
        "max_ms": ms(ordered[-1]),
    }


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - started


def client(api: str) -> httpx.Client:
    c = httpx.Client(base_url=api, timeout=300.0, headers=ORIGIN)
    email = f"perf-{uuid.uuid4().hex[:10]}@example.com"
    r = c.post("/auth/register", json={"email": email, "name": "Perf", "password": PASSWORD})
    r.raise_for_status()
    return c


def large_source(target_bytes: int) -> str:
    chunk = "def handler_{i}(value):\n    total = value + {i}\n    return total * 2\n\n\n"
    parts, size, i = [], 0, 0
    while size < target_bytes:
        piece = chunk.format(i=i)
        parts.append(piece)
        size += len(piece)
        i += 1
    return "".join(parts)


# --- Part A: live HTTP ---------------------------------------------------------------------------


def live(api: str, sizes: list[int]) -> dict[str, Any]:
    results: dict[str, Any] = {"projects": []}
    c = client(api)
    for size in sizes:
        files = fx.large(size)
        pid = c.post("/projects", json={"name": f"Perf {size} {uuid.uuid4().hex[:4]}"}).json()["id"]
        upload_times = []
        for path, content in files.items():
            _, t = timed(
                lambda p=path, b=content: c.post(f"/projects/{pid}/files", json={"path": p, "content": b})
            )
            upload_times.append(t)
        scan, scan_t = timed(lambda: c.post(f"/projects/{pid}/analyze"))
        scan.raise_for_status()
        symbols = scan.json()["statistics"]["total_symbols"]
        search_times = []
        for i in range(30):
            q = f"func_{(i * 7) % size}_{i % 5}"
            r, t = timed(lambda q=q: c.post(f"/projects/{pid}/search", json={"query": q}))
            r.raise_for_status()
            search_times.append(t)
        text_times = []
        for _ in range(10):
            r, t = timed(lambda: c.post(f"/projects/{pid}/search", json={"query": "return total"}))
            text_times.append(t)
        context_times = []
        for i in range(10):
            path = f"pkg/mod{(i * 3) % size}.py"
            r, t = timed(lambda path=path: c.post(f"/projects/{pid}/context", json={"current_file": path}))
            r.raise_for_status()
            context_times.append(t)
        results["projects"].append(
            {
                "files": size,
                "symbols": symbols,
                "upload_total_s": round(sum(upload_times), 2),
                "upload_per_file": summarize(upload_times),
                "project_scan_ms": ms(scan_t),
                "symbol_search": summarize(search_times),
                "text_search": summarize(text_times),
                "context": summarize(context_times),
            }
        )
        if size == sizes[min(1, len(sizes) - 1)]:
            results["concurrency"] = concurrent_search(api, pid, size, dict(c.cookies))

    analysis = {}
    for label, source in (
        ("normal_2kb", large_source(2_000)),
        ("large_1_5mb", large_source(1_500_000)),
    ):
        times = []
        for _ in range(3 if label.startswith("large") else 10):
            r, t = timed(lambda s=source: c.post("/analysis/code", json={"code": s, "language": "python"}))
            r.raise_for_status()
            times.append(t)
        analysis[label] = summarize(times)
    oversized = large_source(2_300_000)
    r, t = timed(lambda: c.post("/analysis/code", json={"code": oversized, "language": "python"}))
    analysis["oversized_2_3mb"] = {"status": r.status_code, "ms": ms(t)}
    results["analysis"] = analysis
    return results


def concurrent_search(
    api: str, pid: str, size: int, cookies: dict[str, str], workers: int = 8, per_worker: int = 25
) -> dict[str, Any]:
    """`workers` clients with the owner's session search one project at the same time."""

    def worker(w: int) -> list[float]:
        c = httpx.Client(base_url=api, timeout=120.0, headers=ORIGIN, cookies=cookies)
        times = []
        for i in range(per_worker):
            q = f"func_{(w * per_worker + i) % size}_{i % 5}"
            r, t = timed(lambda q=q: c.post(f"/projects/{pid}/search", json={"query": q}))
            if r.status_code != 200:
                raise RuntimeError(f"search failed: {r.status_code}")
            times.append(t)
        c.close()
        return times

    started = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        all_times = [t for batch in pool.map(worker, range(workers)) for t in batch]
    wall = time.perf_counter() - started
    return {
        "files": size,
        "workers": workers,
        "requests": len(all_times),
        "wall_s": round(wall, 2),
        "throughput_rps": round(len(all_times) / wall, 1),
        "latency": summarize(all_times),
    }


# --- Part B: in-process with stub providers ------------------------------------------------------


def in_process(sizes: list[int]) -> dict[str, Any]:
    import resource

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from app.services.ai.service import AIService
    from app.services.retrieval.service import RetrievalService
    from tests.ai_stub import StubProvider
    from tests.conftest import build_app, make_settings
    from tests.embedding_stub import StubEmbeddingProvider

    url = os.environ.get("CODEWALK_TEST_DATABASE_URL")
    if not url or not url.rsplit("/", 1)[-1].endswith("_test"):
        return {"skipped": "CODEWALK_TEST_DATABASE_URL (a *_test database) is not set"}
    app = build_app(
        database_url=url,
        ai_enabled=True,
        rag_enabled=True,
        rag_max_chunks_per_run=50_000,
        rag_max_index_runs=1000,
        agent_max_runs=1000,
    )
    app.state.retrieval_service = RetrievalService(
        make_settings(
            rag_enabled=True,
            database_url=url,
            rag_max_chunks_per_run=50_000,
            rag_max_index_runs=1000,
            rag_max_queries=100_000,
        ),
        provider=StubEmbeddingProvider(),
    )
    engine = app.state.database.engine
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_: Any) -> None:
        statements["n"] += 1

    def counted(fn: Callable[[], Any]) -> tuple[Any, float, int]:
        before = statements["n"]
        result, t = timed(fn)
        return result, t, statements["n"] - before

    out: dict[str, Any] = {"projects": []}
    with TestClient(app) as c:
        c.headers.update(ORIGIN)
        c.post(
            "/api/v1/auth/register",
            json={"email": f"perfb-{uuid.uuid4().hex[:8]}@example.com", "name": "Perf", "password": PASSWORD},
        ).raise_for_status()
        for size in sizes:
            pid = c.post("/api/v1/projects", json={"name": f"PerfB {size} {uuid.uuid4().hex[:4]}"}).json()[
                "id"
            ]
            for path, content in fx.large(size).items():
                c.post(f"/api/v1/projects/{pid}/files", json={"path": path, "content": content})
            index, index_t, index_q = counted(lambda: c.post(f"/api/v1/projects/{pid}/rag/index"))
            index.raise_for_status()
            chunks = index.json()["chunks_embedded"]
            semantic, hybrid, queries = [], [], []
            for i in range(20):
                q = f"multiply value by {i} in module {(i * 7) % size}"
                r, t, n = counted(
                    lambda q=q: c.post(
                        f"/api/v1/projects/{pid}/search", json={"query": q, "mode": "semantic"}
                    )
                )
                r.raise_for_status()
                semantic.append(t)
                queries.append(n)
                r, t = timed(
                    lambda q=q: c.post(f"/api/v1/projects/{pid}/search", json={"query": q, "mode": "hybrid"})
                )
                hybrid.append(t)
            _, _, det_q = counted(
                lambda: c.post(f"/api/v1/projects/{pid}/search", json={"query": "func_1_1"})
            )
            steps = [
                {
                    "status_message": "s",
                    "action": "call_tool",
                    "tool": "search_project",
                    "arguments_json": json.dumps({"query": f"func_{k}_0"}),
                    "answer": None,
                }
                for k in range(3)
            ] + [
                {
                    "status_message": "a",
                    "action": "answer",
                    "tool": None,
                    "arguments_json": None,
                    "answer": "ok",
                }
            ]
            agent_times, agent_q = [], []
            for _ in range(5):
                app.state.ai_service = AIService(
                    make_settings(ai_enabled=True, database_url=url),
                    provider=StubProvider(answers=[dict(s) for s in steps]),
                )
                r, t, n = counted(
                    lambda: c.post("/api/v1/agent/run", json={"project_id": pid, "message": "where?"})
                )
                r.raise_for_status()
                agent_times.append(t)
                agent_q.append(n)
            out["projects"].append(
                {
                    "files": size,
                    "chunks": chunks,
                    "index_ms": ms(index_t),
                    "index_sql_statements": index_q,
                    "semantic_search": summarize(semantic),
                    "semantic_sql_statements_median": statistics.median(queries),
                    "hybrid_search": summarize(hybrid),
                    "deterministic_search_sql_statements": det_q,
                    "agent_run_3_tools": summarize(agent_times),
                    "agent_sql_statements_median": statistics.median(agent_q),
                }
            )
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--sizes", default="10,100,500")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]
    report: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
            "api": args.api,
        }
    }
    if not args.skip_live:
        report["live_http"] = live(args.api, sizes)
    if args.in_process:
        report["in_process_stub_providers"] = in_process(sizes)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
