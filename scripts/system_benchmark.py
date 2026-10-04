"""Module 16 system benchmark: large projects, RAG, agent, approvals, and memory, measured in-process.

Runs the real application (``create_app``) with a ``TestClient`` against a dedicated *_test
PostgreSQL database. Project files are written to a temporary workspace folder and linked to a
project, so discovery, the secure scanner, file sync, intelligence, search, semantic indexing,
the agent loop, and proposal approval all run exactly as in production. Embeddings and model
answers come from the test-only stubs (tests/embedding_stub.py, tests/ai_stub.py), so provider
network latency is excluded by design; every number is CodeWalk's own overhead.

Each fixture also contains folders that must never be scanned (node_modules, .git, a virtual
environment, build output) and credential files; the benchmark fails if any of them is stored.

Every number printed is measured; nothing is estimated. SQL statements are counted per request.

Usage (inside the backend test image, next to the compose PostgreSQL):
  CODEWALK_TEST_DATABASE_URL=postgresql+psycopg://...codewalk_test \\
    uv run python ../scripts/system_benchmark.py --sizes 50,500,2000 --out result.json
"""

# ruff: noqa: B023  (every timed lambda runs immediately, inside its loop iteration)

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from tests.fixtures import projects as fx  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
# Single-shot operations (scans, listings, cold index builds) are repeated and summarized:
# one sample on a shared desktop machine varies too much to compare.
REPEATS = 5
PASSWORD = "bench-check-Pass-7"  # noqa: S105 (a throwaway benchmark account)
API = "/api/v1"

# Content that must never reach the database (see app/services/project_intelligence/scanner.py).
NOISE = {
    "node_modules": 300,
    ".git/objects": 100,
    ".venv/lib/site-packages": 200,
    "dist": 100,
    "build": 50,
    "__pycache__": 50,
}
SECRETS = (".env", "secrets.json", "id_rsa", "deploy/credentials.json", ".aws/credentials")


def ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def percentile(ordered: list[float], q: float) -> float:
    return ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))]


def summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    out = {
        "n": len(samples),
        "p50_ms": ms(statistics.median(ordered)),
        "p95_ms": ms(percentile(ordered, 0.95)),
        "max_ms": ms(ordered[-1]),
    }
    if len(samples) >= 100:
        out["p99_ms"] = ms(percentile(ordered, 0.99))
    return out


def rss_mb() -> dict[str, float]:
    """Current and peak resident memory of this process (Linux /proc)."""
    values: dict[str, float] = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, amount = line.split(":", 1)
                values["rss_mb" if key == "VmRSS" else "peak_rss_mb"] = round(
                    int(amount.split()[0]) / 1024, 1
                )
    except OSError:
        pass
    return values


def write_fixture(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for folder, count in NOISE.items():
        base = root / folder
        base.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (base / f"noise_{i}.py").write_text(f"def noise_{i}():\n    return {i}\n", encoding="utf-8")
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for secret in SECRETS:
        target = root / secret
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TOKEN=fake-not-real\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sizes", default="50,500,2000")
    parser.add_argument("--repeat-rounds", type=int, default=3, help="rounds of the memory/leak loop")
    parser.add_argument(
        "--activity-rows", type=int, default=0, help="also time saves/deletes with this many history rows"
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    url = os.environ.get("CODEWALK_TEST_DATABASE_URL")
    if not url or not url.rsplit("/", 1)[-1].endswith("_test"):
        sys.exit("CODEWALK_TEST_DATABASE_URL (a *_test database) is required.")

    from fastapi.testclient import TestClient
    from sqlalchemy import event, func, select
    from sqlalchemy.orm import Session

    from app.db.models import ProjectFile
    from app.services.ai.service import AIService
    from app.services.project_search.index import IndexCache
    from app.services.retrieval.service import RetrievalService
    from tests.ai_stub import StubProvider
    from tests.conftest import build_app, make_settings
    from tests.embedding_stub import StubEmbeddingProvider

    workspace = Path(tempfile.mkdtemp(prefix="codewalk-bench-"))
    limits: dict[str, Any] = {
        "database_url": url,
        "workspace_root": str(workspace),
        "ai_enabled": True,
        "rag_enabled": True,
        "rag_max_chunks_per_run": 50_000,
        "rag_max_index_runs": 10_000,
        "rag_max_queries": 100_000,
        "agent_max_runs": 10_000,
        "ai_max_requests": 10_000,
    }
    app = build_app(**limits)
    embedder = StubEmbeddingProvider()
    app.state.retrieval_service = RetrievalService(make_settings(**limits), provider=embedder)
    engine = app.state.database.engine
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_: Any) -> None:
        statements["n"] += 1

    def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
        started = time.perf_counter()
        result = fn()
        return result, time.perf_counter() - started

    def counted(fn: Callable[[], Any]) -> tuple[Any, float, int]:
        before = statements["n"]
        result, seconds = timed(fn)
        return result, seconds, statements["n"] - before

    def ok(response: Any) -> Any:
        if response.status_code >= 400:
            raise RuntimeError(
                f"{response.request.method} {response.request.url} -> {response.status_code}: "
                f"{response.text[:300]}"
            )
        return response

    def agent_steps(queries: list[str]) -> list[dict[str, Any]]:
        steps = [
            {
                "status_message": "Searching",
                "action": "call_tool",
                "tool": "search_project",
                "arguments_json": json.dumps({"query": q}),
                "answer": None,
            }
            for q in queries
        ]
        return [
            *steps,
            {
                "status_message": "Done",
                "action": "answer",
                "tool": None,
                "arguments_json": None,
                "answer": "Found it.",
            },
        ]

    report: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
            "providers": "stub embedder + stub model (provider latency excluded)",
        },
        "projects": [],
    }

    with TestClient(app) as c:
        c.headers.update(ORIGIN)
        ok(
            c.post(
                f"{API}/auth/register",
                json={
                    "email": f"bench-{uuid.uuid4().hex[:8]}@example.com",
                    "name": "Bench",
                    "password": PASSWORD,
                },
            )
        )
        report["memory_start"] = rss_mb()

        for size in sizes:
            folder = f"bench{size}_{uuid.uuid4().hex[:6]}"
            files = fx.large(size)
            write_fixture(workspace / folder, files)
            row: dict[str, Any] = {"files": size}

            pid = ok(c.post(f"{API}/projects", json={"name": f"Bench {folder}", "root_path": folder})).json()[
                "id"
            ]

            scan, t, q = counted(lambda: ok(c.post(f"{API}/projects/{pid}/analyze")))
            body = scan.json()
            with Session(engine) as session:
                stored_paths = set(
                    session.scalars(select(ProjectFile.path).where(ProjectFile.project_id == pid))
                )
            leaked = sorted(p for p in stored_paths if p not in files)
            if leaked:
                raise RuntimeError(f"ignored or secret files were stored: {leaked[:5]}")
            row["first_scan"] = {
                "ms": ms(t),
                "sql_statements": q,
                "stored_files": len(stored_paths),
                "skipped_entries": body.get("statistics", {}).get("skipped_files"),
                "symbols": body["statistics"]["total_symbols"],
            }

            def repeated(fn: Callable[[], Any], n: int = REPEATS) -> tuple[Any, dict[str, Any]]:
                """Run ``fn`` n times: the last response, timing summary, and median SQL statements."""
                samples, queries, response = [], [], None
                for _ in range(n):
                    response, t, q = counted(fn)
                    samples.append(t)
                    queries.append(q)
                return response, {**summarize(samples), "sql_statements": statistics.median(queries)}

            _, row["rescan_unchanged"] = repeated(lambda: ok(c.post(f"{API}/projects/{pid}/analyze")))
            listing, row["list_files"] = repeated(
                lambda: ok(c.get(f"{API}/projects/{pid}/files", params={"limit": 10_000}))
            )
            items = listing.json()["items"]
            row["list_files"]["bytes"] = len(listing.content)
            intel, row["intelligence_view"] = repeated(
                lambda: ok(c.get(f"{API}/projects/{pid}/intelligence"))
            )
            row["intelligence_view"]["bytes"] = len(intel.content)

            ids = [item["id"] for item in items]
            opens, open_q = [], []
            for i in range(20):
                fid = ids[(i * 37) % len(ids)]
                _, t, q = counted(lambda fid=fid: ok(c.get(f"{API}/projects/{pid}/files/{fid}")))
                opens.append(t)
                open_q.append(q)
            row["open_file"] = {**summarize(opens), "sql_statements": statistics.median(open_q)}

            # Search with no cached project index (cold: the index is built from all stored files).
            def cold_search() -> Any:
                app.state.search_index_cache = IndexCache()
                return ok(c.post(f"{API}/projects/{pid}/search", json={"query": "func_1_1"}))

            _, row["search_cold"] = repeated(cold_search)

            # Search right after one file changed (edit on disk + rescan, not timed): the index is
            # brought up to date before the search runs.
            edited = workspace / folder / "pkg" / "mod0.py"
            original_text = edited.read_text(encoding="utf-8")
            after_edit = []
            for k in range(REPEATS):
                edited.write_text(original_text + f"\n\ndef edited_{k}(x):\n    return x\n", encoding="utf-8")
                ok(c.post(f"{API}/projects/{pid}/analyze"))
                _, t, q = counted(
                    lambda k=k: ok(c.post(f"{API}/projects/{pid}/search", json={"query": f"edited_{k}"}))
                )
                after_edit.append((t, q))
            edited.write_text(original_text, encoding="utf-8")
            ok(c.post(f"{API}/projects/{pid}/analyze"))
            row["search_after_one_edit"] = {
                **summarize([t for t, _ in after_edit]),
                "sql_statements": statistics.median([q for _, q in after_edit]),
            }
            sym, sym_q, defining_first = [], [], 0
            for i in range(30):
                module = (i * 7) % size
                query = f"func_{module}_{i % 5}"
                response, t, q = counted(
                    lambda query=query: ok(c.post(f"{API}/projects/{pid}/search", json={"query": query}))
                )
                sym.append(t)
                sym_q.append(q)
                top = response.json()["results"][:1]
                defining_first += bool(top) and top[0]["file_path"] == f"pkg/mod{module}.py"
            row["symbol_search"] = {
                **summarize(sym),
                "sql_statements": statistics.median(sym_q),
                # Correctness: how often the file defining the searched function ranks first.
                "defining_file_first": f"{defining_first}/30",
            }
            text_t = []
            for _ in range(10):
                r, t = timed(
                    lambda: ok(c.post(f"{API}/projects/{pid}/search", json={"query": "return total"}))
                )
                text_t.append(t)
            row["text_search"] = {**summarize(text_t), "results": r.json()["total"]}
            ctx = []
            for i in range(10):
                path = f"pkg/mod{(i * 3) % size}.py"
                _, t = timed(
                    lambda path=path: ok(
                        c.post(f"{API}/projects/{pid}/context", json={"current_file": path, "line": 3})
                    )
                )
                ctx.append(t)
            row["context"] = summarize(ctx)

            # Semantic index: full, unchanged (incremental), then one changed file.
            calls_before = len(embedder.calls)
            first, t, q = counted(lambda: ok(c.post(f"{API}/projects/{pid}/rag/index")))
            row["rag_index_full"] = {
                "ms": ms(t),
                "sql_statements": q,
                "chunks_embedded": first.json()["chunks_embedded"],
                "provider_calls": len(embedder.calls) - calls_before,
            }
            calls_before = len(embedder.calls)
            again, t, q = counted(lambda: ok(c.post(f"{API}/projects/{pid}/rag/index")))
            row["rag_index_unchanged"] = {
                "ms": ms(t),
                "sql_statements": q,
                "chunks_embedded": again.json()["chunks_embedded"],
                "provider_calls": len(embedder.calls) - calls_before,
            }
            target = workspace / folder / "pkg" / "mod1.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n\ndef added_helper(x):\n    return x\n",
                encoding="utf-8",
            )
            ok(c.post(f"{API}/projects/{pid}/analyze"))
            calls_before = len(embedder.calls)
            changed, t, q = counted(lambda: ok(c.post(f"{API}/projects/{pid}/rag/index")))
            body = changed.json()
            row["rag_index_one_file_changed"] = {
                "ms": ms(t),
                "sql_statements": q,
                "files_indexed": body["files_indexed"],
                "chunks_embedded": body["chunks_embedded"],
                "chunks_reused": body["chunks_reused"],
                "provider_calls": len(embedder.calls) - calls_before,
            }
            sem, hyb, sem_q = [], [], []
            for i in range(20):
                query = f"multiply value by {i} in module {(i * 7) % size}"
                _, t, q = counted(
                    lambda query=query: ok(
                        c.post(f"{API}/projects/{pid}/search", json={"query": query, "mode": "semantic"})
                    )
                )
                sem.append(t)
                sem_q.append(q)
                _, t = timed(
                    lambda query=query: ok(
                        c.post(f"{API}/projects/{pid}/search", json={"query": query, "mode": "hybrid"})
                    )
                )
                hyb.append(t)
            row["semantic_search"] = {**summarize(sem), "sql_statements": statistics.median(sem_q)}
            row["hybrid_search"] = summarize(hyb)

            # Agent: three read-only tool calls and an answer, through the real loop and policy.
            agent_t, agent_q = [], []
            for k in range(10):
                app.state.ai_service = AIService(
                    make_settings(**limits),
                    provider=StubProvider(answers=agent_steps([f"func_{k}_0", "return total", f"mod{k}"])),
                )
                run, t, q = counted(
                    lambda: ok(c.post(f"{API}/agent/run", json={"project_id": pid, "message": "where?"}))
                )
                if len(run.json()["tool_calls"]) != 3:
                    raise RuntimeError("the agent did not run the expected tools")
                agent_t.append(t)
                agent_q.append(q)
            row["agent_run_3_tools"] = {**summarize(agent_t), "sql_statements": statistics.median(agent_q)}

            # Module 17: deterministic insights (skipped on servers that do not have them).
            target = f"pkg/mod{size // 2}.py"
            symbol = f"func_{size // 2}_0"
            probe = c.get(f"{API}/projects/{pid}/architecture")
            if probe.status_code == 200:
                _, row["architecture"] = repeated(lambda: ok(c.get(f"{API}/projects/{pid}/architecture")))
                impact, row["impact_analysis"] = repeated(
                    lambda: ok(
                        c.post(f"{API}/projects/{pid}/impact", json={"file_path": target, "symbol": symbol})
                    )
                )
                body = impact.json()
                row["impact_analysis"]["result"] = {
                    "direct": len(body["direct_dependents"]),
                    "indirect": len(body["indirect_dependents"]),
                    "possible": len(body["possible_references"]),
                }
                _, row["references"] = repeated(
                    lambda: ok(c.post(f"{API}/projects/{pid}/references", json={"name": symbol}))
                )
                review_t, prompt_chars = [], []
                finding = {
                    "severity": "low",
                    "category": "maintainability",
                    "title": "Magic number",
                    "file_path": target,
                    "start_line": 3,
                    "explanation": "x",
                    "evidence": "total = value + 0",
                    "confidence": "low",
                }
                for _ in range(5):
                    app.state.ai_service = AIService(
                        make_settings(**limits),
                        provider=StubProvider(
                            answers=[
                                _tool("analyze_impact", file_path=target, symbol=symbol),
                                _tool("get_file_content", file_path=target),
                                _tool("record_finding", **finding),
                                agent_steps([])[-1],
                            ]
                        ),
                    )
                    run, t = timed(
                        lambda: ok(
                            c.post(
                                f"{API}/agent/run",
                                json={"project_id": pid, "message": "review", "mode": "review"},
                            )
                        )
                    )
                    review_t.append(t)
                    prompt_chars.append(run.json()["usage"]["largest_prompt_chars"])
                row["agent_review_3_tools"] = {
                    **summarize(review_t),
                    "largest_prompt_chars_median": statistics.median(prompt_chars),
                }
            row["memory_after"] = rss_mb()
            report["projects"].append(row)
            print(json.dumps(row), flush=True)

        # Proposal approval on a writable project, and a repeated-operations loop for memory growth.
        wpid = ok(c.post(f"{API}/projects", json={"name": f"Bench writable {uuid.uuid4().hex[:6]}"})).json()[
            "id"
        ]
        code = "def total(items):\n    for item in items:\n        total += item\n    return total\n"
        fid = ok(c.post(f"{API}/projects/{wpid}/files", json={"path": "cart.py", "content": code})).json()[
            "file"
        ]["id"]
        approvals, approve_q = [], []
        for k in range(10):
            edits = [
                {"start_line": 2, "end_line": 2, "replacement": f"    total = {k}\n    for item in items:"}
            ]
            app.state.ai_service = AIService(
                make_settings(**limits),
                provider=StubProvider(
                    answers=[
                        {
                            "status_message": "Proposing",
                            "action": "call_tool",
                            "tool": "propose_fix",
                            "arguments_json": json.dumps(
                                {
                                    "file_path": "cart.py",
                                    "summary": "init",
                                    "explanation": "x",
                                    "edits": edits,
                                }
                            ),
                            "answer": None,
                        },
                        {
                            "status_message": "Done",
                            "action": "answer",
                            "tool": None,
                            "arguments_json": None,
                            "answer": "ok",
                        },
                    ]
                ),
            )
            run = ok(c.post(f"{API}/agent/run", json={"project_id": wpid, "message": "fix"})).json()
            action = run["actions"][0]["id"]
            _, t, q = counted(lambda: ok(c.post(f"{API}/agent/actions/{action}/approve")))
            approvals.append(t)
            approve_q.append(q)
            ok(
                c.patch(f"{API}/projects/{wpid}/files/{fid}", json={"content": code})
            )  # reset for the next round
        report["approve_proposal"] = {**summarize(approvals), "sql_statements": statistics.median(approve_q)}

        loop: list[dict[str, Any]] = []
        for _ in range(args.repeat_rounds):
            for i in range(200):
                ok(c.post(f"{API}/projects/{wpid}/search", json={"query": f"total {i}"}))
            for i in range(50):
                ok(c.patch(f"{API}/projects/{wpid}/files/{fid}", json={"content": code + f"# edit {i}\n"}))
                ok(c.get(f"{API}/projects/{wpid}/files/{fid}"))
            for i in range(20):
                app.state.ai_service = AIService(
                    make_settings(**limits), provider=StubProvider(answers=agent_steps([f"total {i}"]))
                )
                ok(c.post(f"{API}/agent/run", json={"project_id": wpid, "message": "where?"}))
            loop.append(rss_mb())
        report["repeated_operations_memory"] = {
            "per_round": "200 searches + 50 saves + 50 file opens + 20 agent runs",
            "rounds": loop,
        }
        with Session(engine) as session:
            report["database_rows"] = {
                "files": session.scalar(select(func.count()).select_from(ProjectFile)),
            }

        if args.activity_rows:
            report["large_history"] = large_history(c, engine, ok, counted, args.activity_rows)

    report["memory_end"] = rss_mb()
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


def _tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "status_message": "Working",
        "action": "call_tool",
        "tool": name,
        "arguments_json": json.dumps(arguments),
        "answer": None,
    }


def large_history(c: Any, engine: Any, ok: Any, counted: Any, rows: int) -> dict[str, Any]:
    """Saves and deletes while ``activity_events`` holds ``rows`` rows (a long-lived installation).

    Every save beyond ``analysis_history_per_file`` prunes the oldest analysis of that file, and
    deleting a file or an analysis makes PostgreSQL clear ``activity_events`` references to it
    (ON DELETE SET NULL). The rows are seeded for a throwaway user and removed afterwards.
    """
    from sqlalchemy import text

    email = f"bench-history-{uuid.uuid4().hex[:8]}@example.com"
    ok(c.post(f"{API}/auth/logout"))
    ok(c.post(f"{API}/auth/register", json={"email": email, "name": "Bench", "password": PASSWORD}))
    with engine.begin() as connection:
        user_id = connection.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar_one()
        connection.execute(
            text(
                "INSERT INTO activity_events (id, user_id, event_type, project_name, details, created_at) "
                "SELECT gen_random_uuid(), :u, 'file.updated', 'seed', '{}'::jsonb, now() "
                "FROM generate_series(1, :n)"
            ),
            {"u": user_id, "n": rows},
        )
        connection.execute(text("ANALYZE activity_events"))
    try:
        pid = ok(c.post(f"{API}/projects", json={"name": f"History {uuid.uuid4().hex[:6]}"})).json()["id"]
        fid = ok(c.post(f"{API}/projects/{pid}/files", json={"path": "a.py", "content": "x = 0\n"})).json()[
            "file"
        ]["id"]
        for i in range(25):  # past the per-file analysis history limit (20): every later save prunes one
            ok(c.patch(f"{API}/projects/{pid}/files/{fid}", json={"content": f"x = {i + 1}\n"}))
        saves, save_q = [], []
        for i in range(30):
            _, t, q = counted(
                lambda i=i: ok(c.patch(f"{API}/projects/{pid}/files/{fid}", json={"content": f"y = {i}\n"}))
            )
            saves.append(t)
            save_q.append(q)
        deletes = []
        for i in range(20):
            other = ok(
                c.post(f"{API}/projects/{pid}/files", json={"path": f"d{i}.py", "content": "z = 1\n"})
            ).json()
            _, t, _q = counted(
                lambda other=other: ok(c.delete(f"{API}/projects/{pid}/files/{other['file']['id']}"))
            )
            deletes.append(t)
        return {
            "activity_events_rows": rows,
            "save_with_prune": {**summarize(saves), "sql_statements": statistics.median(save_q)},
            "delete_file": summarize(deletes),
        }
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


if __name__ == "__main__":
    main()
