# Performance report (Module 14)

All numbers below were measured on 2026-10-03 with `scripts/performance.py` (`npm run test:perf`).
Nothing is estimated. Setup time (creating users, uploading the synthetic projects) is reported
separately from the application operations being measured.

## Environment

| Item | Value |
| --- | --- |
| Host | Windows 11 (10.0.26200), 8 logical CPUs, Docker Desktop (WSL2) |
| Backend | `codewalk-backend-test:local` image (Python 3.12, uvicorn, 1 process), Linux container |
| Database | `pgvector/pgvector:pg17-bookworm` (PostgreSQL 17.11, pgvector 0.8.7), same Docker network |
| Part A client | Python 3.12 on the Windows host, `httpx`, over Docker Desktop port forwarding (adds latency to every request) |
| Part B | in-process (`TestClient`) inside the Linux container, against the `codewalk_test` database |
| Providers | none: AI and Voyage are not configured. Part B uses the test-only stub embedder and stub model, so provider network latency is **excluded by design** |

Workload: synthetic Python projects from `tests/fixtures/projects.large(n)`: `n` modules, each
importing the previous one, 5 functions per module (10, 100, 500 files; 50, 500, 2,500 symbols).

## Part A — live HTTP (real backend and database)

| Operation | 10 files | 100 files | 500 files |
| --- | --- | --- | --- |
| Setup: upload all files (total) | 0.22 s | 2.09 s | 10.82 s |
| Upload one file (p50 / p95), includes save + version + analysis | 22.0 / 24.2 ms | 20.5 / 23.1 ms | 20.7 / 27.2 ms |
| Project scan / intelligence (`POST /analyze`) | 16.9 ms | 56.7 ms | 247.6 ms |
| Symbol search, 30 queries (p50 / p95 / max) | 12.1 / 14.5 / 16.9 ms | 29.5 / 36.3 / 103.1 ms | 43.2 / 127.6 / 205.7 ms |
| Text search, 10 queries (p50 / p95) | 9.5 / 13.7 ms | 25.9 / 106.1 ms | 42.7 / 124.9 ms |
| Context builder, 10 calls (p50 / p95) | 7.8 / 9.9 ms | 8.7 / 10.0 ms | 11.4 / 13.3 ms |

Deterministic analysis (`POST /analysis/code`, Python):

| Input | Result |
| --- | --- |
| Normal file (~2 KB), 10 runs | p50 7.3 ms, p95 9.9 ms |
| Large file (~1.5 MB, ~19,000 functions), 3 runs | p50 623 ms, max 675 ms |
| Oversized file (~2.3 MB, above the 2 MB limit) | rejected with **413** in 39 ms (not analyzed) |

Concurrency (100-file project, 8 clients × 25 symbol searches, same user):

| Requests | Wall time | Throughput | Latency p50 / p95 / max |
| --- | --- | --- | --- |
| 200 | 7.01 s | 28.5 requests/s | 263.9 / 372.6 / 430.3 ms |

## Part B — in-process, stub providers (CodeWalk overhead only)

| Operation | 10 files | 100 files | 500 files |
| --- | --- | --- | --- |
| Chunks produced | 59 | 599 | 2,999 |
| Semantic index run (all chunks) | 123 ms | 624 ms | 4,156 ms |
| SQL statements per index run | 30 | 212 | 1,021 |
| Semantic search, 20 queries (p50 / p95) | 13.9 / 18.2 ms | 30.2 / 40.0 ms | 109.6 / 135.6 ms |
| Hybrid search (p50 / p95) | 14.3 / 18.2 ms | 31.6 / 37.1 ms | 107.2 / 121.3 ms |
| SQL statements per semantic search (median) | 14 | 14 | 14 |
| SQL statements per deterministic search | 3 | 3 | 3 |
| Agent run, 3 tool calls + answer (p50 / p95) | 27.6 / 68.3 ms | 86.2 / 175.3 ms | 124.7 / 217.0 ms |
| SQL statements per agent run (median) | 14 | 14 | 14 |

Peak resident memory of the Part B process (app, test client, all three projects): **220 MB**.

## Database behavior

- Deterministic search issues a constant 3 statements regardless of project size: the project
  index is cached in memory per project and invalidated by a content-hash fingerprint.
- Semantic search issues a constant 14 statements (ownership, index status, savepointed vector
  query, HNSW session settings); its time grows with chunk count (pgvector HNSW scan with
  `iterative_scan` and an exact re-sort).
- Indexing issues roughly one statement per chunk plus per-file reads: one `INSERT` per chunk.

## Bottlenecks and recommendations

1. **Indexing inserts row by row** (1,021 statements for 2,999 chunks at 500 files). Batch
   inserts would cut index time substantially; with a real provider, embedding latency will
   dominate anyway (not measured here: no Voyage key).
2. **Search at 500 files**: p95 of about 125 ms for symbol and text search comes from scanning
   every file's symbols and lines in Python. Acceptable for the project sizes CodeWalk targets;
   a token index would help beyond a few thousand files.
3. **Concurrency** is bounded by one backend process (latency rises to about 264 ms p50 at 8
   concurrent clients). Production should run several workers; rate limits are then
   per process (see the security report).
4. **Large-file analysis** (~0.6 s for 1.5 MB) is dominated by the analyzers themselves; the
   2 MB limit holds and oversized input is refused cheaply.

## Not measured

- Real AI and embedding provider latency (no credentials configured; the live-provider tests
  were skipped). Part B numbers exclude provider time by design.
- Frontend rendering performance (Monaco, large diffs) beyond the functional browser checks.
