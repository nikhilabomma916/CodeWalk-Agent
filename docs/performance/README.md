# Performance (Module 16)

Every number here is **MEASURED** unless it is explicitly marked **EXPECTED**. Nothing is
estimated. Baseline = `develop` at `990fb29` (Module 15); after = this branch. Both were measured
with the same script on the same machine, one after the other, with nothing else running.

## How to reproduce

```bash
# Linux backend test image next to the compose PostgreSQL (see scripts/test-all.mjs)
docker build -t codewalk-backend-test:local -f docker/backend-test/Dockerfile backend
docker run --rm --network codewalk_default -e CODEWALK_TEST_DATABASE_URL \
  -v "$PWD/scripts:/work/scripts:ro" codewalk-backend-test:local \
  uv run python /work/scripts/system_benchmark.py --sizes 50,500,2000 --activity-rows 300000
```

`scripts/system_benchmark.py` runs the real application in-process (`TestClient`) against a `*_test`
database. Each project is a folder linked to a project, so discovery, the secure scanner, sync,
intelligence, search, semantic indexing, the agent loop and approvals run as in production. The
folder also contains `node_modules`, `.git`, a virtual environment, build output and credential
files; the script fails if any of them is stored. The Module 14 HTTP benchmark
(`scripts/performance.py`) is unchanged.

## Test conditions

| Item | Value |
| --- | --- |
| Host | Windows 11, 8 logical CPUs, Docker Desktop (WSL2) |
| Backend | Python 3.12, in-process, 1 worker, Linux container |
| Database | `pgvector/pgvector:pg17-bookworm`, same Docker network |
| Providers | test-only stub embedder and stub model: **provider latency is excluded**; the numbers are CodeWalk's own overhead |
| Dataset | synthetic Python projects: N modules, each importing the previous one, 5 functions each (50/500/2,000 files; 250/2,500/10,000 symbols; 299/2,999/11,999 chunks) |
| Concurrency | sequential requests (concurrency is covered by tests, see operations) |
| Samples | timed loops: 20-30 requests (search, open file), 10 (agent, context, text search); single-shot operations repeated 5 times; p50 / p95 reported |
| Error rate | 0: every request returned 2xx (the script fails otherwise) |

## Results: 2,000 files (largest project)

| Operation | Baseline p50 / p95 | After p50 / p95 | SQL statements |
| --- | --- | --- | --- |
| Link and import the folder (first scan) | 6,855 ms | 2,033 ms | 8,008 -> 12 |
| Rescan, nothing changed | 861 / 1,097 ms | 904 / 970 ms | 7 -> 7 |
| Search right after one file changed | 636 / 782 ms | 177 / 192 ms | 4 |
| Search, no cached index (cold) | 604 / 701 ms | 712 / 895 ms | 4 |
| Symbol search (index cached) | 48 / 175 ms | 146 / 303 ms | 3 |
| -- of which: defining file ranked first | **3 / 30** | **30 / 30** | |
| Text search | 44 / 191 ms | 118 / 138 ms | |
| Semantic search | 406 / 519 ms | 87 / 169 ms | 14 -> 13 |
| Hybrid search | 401 / 452 ms | 216 / 268 ms | |
| Semantic index, full (11,999 chunks) | 14,734 ms | 12,058 ms | 4,054 -> 110 |
| Semantic index, one file changed | 587 ms | 140 ms | 11 -> 10 |
| Semantic index, nothing changed | 109 ms | 62 ms | 7 -> 6 |
| Context for a file | 15 / 17 ms | 20 / 25 ms | |
| Open a file | 9 / 12 ms | 7 / 9 ms | 3 |
| List files (2,000) | 46 / 164 ms | 49 / 194 ms | 4 |
| Intelligence view (5.3 MB) | 542 / 556 ms | 563 / 671 ms | 4 |
| Agent run, 3 search tools + answer (stub model) | 306 / 438 ms | 366 / 480 ms | 14 |
| Approve a proposal | 26 / 43 ms | 36 / 54 ms | 22 |

**Correctness came first.** Before this module, deterministic search stopped collecting after
1,000 candidates in file-path order, so in large projects it returned weaker matches and dropped
the file that defines the searched symbol (3 of 30 queries correct at 2,000 files, 18 of 30 at 500).
Every file is now examined (the best 1,000 are kept). That costs about 100 ms per deterministic
search at 2,000 files (48 -> 146 ms p50), and agent runs that search pay it per tool call. A
whole-file pre-check, cached name splitting and lazy result construction keep the full scan to
that cost; results are identical to an unbounded search.

Rows with unchanged code (rescan, listing, intelligence view) vary between runs on this machine by
about +-15% (two baseline runs measured the 2,000-file rescan at 760 and 861 ms).

## Results: 50 and 500 files

| Operation (p50) | 50 files: before -> after | 500 files: before -> after |
| --- | --- | --- |
| First scan | 166 -> 61 ms | 1,723 -> 448 ms |
| Search after one edit | 21 -> 11 ms | 156 -> 50 ms |
| Symbol search (defining file first) | 16 -> 9 ms (30/30 -> 30/30) | 45 -> 42 ms (18/30 -> 30/30) |
| Semantic search | 22 -> 12 ms | 110 -> 32 ms |
| Hybrid search | 22 -> 16 ms | 110 -> 61 ms |
| Semantic index, full | 310 -> 283 ms | 3,409 -> 2,649 ms |
| Semantic index, one file changed | 27 -> 25 ms | 202 -> 50 ms |
| Agent run (3 tools) | 49 -> 30 ms | 145 -> 106 ms |

## RAG

- Incremental indexing works: re-indexing an unchanged project embeds **0** chunks and makes **0**
  provider calls; after one file changed, only that file is re-chunked: 1 chunk embedded, 6 reused,
  **1** provider call (all sizes).
- Results are bounded: at most `limit` hits (fusion uses 50 deterministic + 20 semantic), filtered by
  project and by the file's current content hash; tests cover stale chunks, ownership, and
  cross-user retrieval (`test_retrieval_api.py`, `test_module16_workflows.py`).
- A full index is dominated by PostgreSQL maintaining the HNSW index; CodeWalk's own statements
  dropped from 4,054 to 110 (lookups per 200 files, one DELETE per group, batched INSERTs, vectors
  encoded with the C `json` module).
- **EXPECTED, not measured:** with the real provider (Voyage), embedding latency will dominate a
  full index; no credential was available.

## Agent

- Stub model, 3 tool calls + answer: 30 / 106 / 366 ms p50 for 50 / 500 / 2,000 files; 14 SQL
  statements per run regardless of size. Time is the deterministic search inside the tools.
- Loops, repeated identical calls, step/time/context limits and proposal limits end runs safely
  (`test_agent_api.py`). Run limits hold under concurrency (`test_simultaneous_agent_runs_...`).
- **EXPECTED, not measured:** with a real model each step adds provider latency (seconds); the run
  is bounded by `CODEWALK_AGENT_TIMEOUT_SECONDS` (240 s) and 8 steps.

## Database

| Change | Benefit (measured) |
| --- | --- |
| Partial index `activity_events (analysis_id) WHERE analysis_id IS NOT NULL` | A save that prunes an old analysis (every save past 20 per file), with 300,000 history rows: **36.7 -> 20.4 ms** p50 (45.3 -> 24.0 p95). Without it, every pruned analysis made PostgreSQL scan the whole history table, which only grows. |
| Partial index `activity_events (file_id) WHERE file_id IS NOT NULL` | Deleting a file with 300,000 history rows: **25.4 -> 10.5 ms** p50. Also used by folder rescans that remove files. |
| Batched folder import | 8,008 -> 12 statements for 2,000 files. |
| Batched semantic index writes | 4,054 -> 110 statements for 11,999 chunks. |
| Statement timeout (30 s) | A stuck query can no longer hold one of the pooled connections indefinitely. |

Neither index duplicates an existing one (the foreign-key audit query and `pg_indexes` showed no
index on these columns). Indexes considered and **not** added: `agent_actions.project_id` and
`file_versions.author_id` are only used by project or user deletion, which are rare and touch small
tables. The migration builds the indexes `CONCURRENTLY` (no write lock) and rebuilds an invalid
index left by an interrupted run; `test_migrations.py` round-trips it.

## Frontend

| Measurement | Result |
| --- | --- |
| Explorer renders per 3 keystrokes, 400 visible files (vitest, `project-explorer.test.tsx`) | **1,200 -> 1** |
| Browser, 2,002-file project: file list request | 70 ms |
| Browser: open a file / live analysis | 17 ms / 34 ms |
| Browser: editor instances | 1 (Monaco is not recreated) |
| Browser: JS heap after loading the large project | 24 MB |
| Browser: project page tree | 2,004 items rendered (not virtualized) |

Browser numbers come from Chrome's Performance API against the local production build; the tab was
in the background, so timer-based page-load figures are not reported.

## Memory

| Measurement | Result |
| --- | --- |
| Backend RSS after the 50 / 500 / 2,000-file projects (cumulative, one process) | 168 / 196 / 305 MB (baseline 171 / 199 / 318 MB) |
| Repeated operations: 3 rounds of 200 searches + 50 saves + 50 file opens + 20 agent runs | 304 -> 304 -> 304 MB: no growth, no leak observed |
| Peak RSS | 322 MB |

PostgreSQL and frontend server memory were not profiled beyond the container health checks.
These figures come from one machine; they do not establish production scalability.

## Docker (Module 15 infrastructure, this branch)

`npm run test:deploy` (own compose project `codewalk-smoke`, throwaway volume): image build 26.1 s,
cold stack ready 12.7 s (database 2.3 s, migration job 2.0 s, backend 4.3 s), smoke tests 7/7 before
and after a restart with the same volume, ready after restart 10.2 s. In the running stack:
migration head `9c4d2b7a1e83`, both new indexes present, `/metrics` answered on the internal network
with route-template labels only, and not reachable through the proxy.
