# System integration (Module 16)

How the modules of CodeWalk Agent work together, what the Module 16 audit found, and what was
changed. Performance numbers are in [../performance/README.md](../performance/README.md);
operations (metrics, limits, known limitations) in [../operations/README.md](../operations/README.md).

## Request path

```text
Browser
  -> Next.js frontend (proxy.ts: per-request CSP nonce)              frontend/proxy.ts
  -> API client: fetch with credentials, timeout, abort, zod check   frontend/services/api/client.ts
  -> nginx: /api/ only (production)                                  deploy/nginx/codewalk/locations.conf
  -> FastAPI middleware: CORS -> request id + security headers +     backend/app/core/middleware.py
     access log + metrics -> Origin check (CSRF) -> body size limit
  -> route -> dependencies: session cookie -> AuthService -> User     backend/app/api/deps.py
  -> services, every one constructed for the signed-in user          backend/app/services/
     ProjectService.get(): another user's project is "not found"
  -> repositories (flush, never commit) -> PostgreSQL + pgvector     backend/app/repositories/
```

Feature chains, all behind the same ownership check:

| Chain | Path |
| --- | --- |
| Code analysis | editor (debounced, cancellable) -> `POST /analysis/code` -> AnalysisEngine (Ruff, TypeScript worker, tree-sitter, ...) -> diagnostics; never stored. Saving a file stores an analysis (history capped per file). |
| Project intelligence | stored files (or a linked folder: secure scanner -> sync) -> per-file structure cached by content hash in `files.structure` -> imports and relationships -> `analyses` row |
| Search | in-memory `ProjectIndex` per project (process-local LRU, keyed by every file's content hash) -> deterministic ranking; semantic/hybrid add pgvector similarity |
| RAG | `POST /rag/index`: chunks of new/changed files -> embeddings (reused per chunk hash) -> `code_chunks`; queries are filtered by project and by the file's current content hash |
| AI | request -> ownership -> project context (deterministic + semantic) -> prompt -> provider -> schema validation -> normalization against the real file |
| Agent | run -> policy-checked tool loop (READ_ONLY and PROPOSED_CHANGE only; WRITE is never callable by the model) -> proposals stored as `pending` |
| Approval | `POST /agent/actions/{id}/approve` -> action row and file row locked -> content-hash and range re-check -> FileService save (new version, re-analysis, history) -> diagnostics returned -> UI refresh |

## Audit: problems found and fixed

Each item was found by reading the code (or, for #10, in the browser) and confirmed by a
measurement or a failing test before it was changed.

| # | Problem | Evidence (baseline 990fb29) | Change |
| --- | --- | --- | --- |
| 1 | Two **different** proposals for the same file, approved at the same time, could both pass the content-hash check; the second silently overwrote the first (a lost update). | New test `test_different_proposals_for_one_file_cannot_both_apply`: both approvals returned 200 in 3 of 3 runs. | Approval locks the file row (`SELECT ... FOR UPDATE`) before checking the hash; the second approval now sees the first's content and is reported `stale` (409). |
| 2 | Rate limits checked and recorded in two steps: simultaneous requests all passed the check before any was recorded. | `test_simultaneous_agent_runs_cannot_exceed_the_run_limit`: with a limit of 2, 4 runs were admitted (2 of 3 runs). | `AttemptLimiter.acquire()` checks and records atomically; used for login, registration, AI, agent runs, semantic queries and index runs. |
| 3 | Semantic-mode search computed (and discarded) the full deterministic match list. | Profile, 2,000 files: about 70% of a semantic search was deterministic matching. | Deterministic matching runs only for hybrid fusion or the deterministic fallback. |
| 4 | Any file change made the next search, context, AI or agent request rebuild the whole project index (reload every file, re-validate every cached structure, rebuild all relationships). | Profile: 0.8 s at 2,000 files for one edited file. | `ProjectIndex.assemble` reuses unchanged files and loads only files whose content hash changed; imports are resolved again for all files with the same resolver project intelligence uses, so the result equals a full rebuild (unit-tested for edits, additions, deletions, renames and tsconfig changes). |
| 5 | Semantic indexing: one lookup and one delete per file, inserts split per file by the ORM, vectors encoded in a Python loop. | 4,054 SQL statements for 11,999 chunks; ~1.2 s of 5.9 s spent formatting vectors (500-file profile). | Stored vectors looked up per 200 files, one DELETE per group, Core `INSERT` batches, vectors encoded/decoded with the C `json` module. |
| 6 | Linking a folder inserted each new file and its first version with 4 statements per file. | 8,008 statements for 2,000 files. | New files and their version 1 are added in one flush (no max-version query, nothing to prune). |
| 7 | `activity_events.file_id` and `.analysis_id` had no index although rows they reference are deleted during normal use (`ON DELETE SET NULL`). Every save past the analysis-history limit prunes an analysis, so PostgreSQL scanned the whole history table on each such save. | See the large-history measurement in the performance report. | Partial indexes (`IS NOT NULL`), created `CONCURRENTLY` by migration `9c4d2b7a1e83`. |
| 8 | No limit on how long one SQL statement may run: a stuck query holds one of the (at most 10) pooled connections indefinitely. | Code review. | `CODEWALK_DATABASE_STATEMENT_TIMEOUT_SECONDS` (default 30 s) on application connections; migrations are unaffected. |
| 9 | No metrics: latency and error rates were only visible by reading access logs. | Code review. | Bounded Prometheus metrics at backend `GET /metrics` (see operations). |
| 10 | **Deterministic search lost exact matches in large projects.** Collection stopped once 1,000 candidates were found, in file-path order, so a symbol defined in a "late" file was never examined: in a 2,000-file project, searching `func_1500_3` returned weaker partial matches from `pkg/mod0.py`, `pkg/mod10.py`, ... and not the defining file. | Found in the browser (Workflow E); new test `test_exact_match_in_a_late_file_is_not_lost_in_a_large_project` fails on the baseline. | Every file is examined; the 1,000 best-ranked candidates are kept with a bounded heap (`heapq.nsmallest`), and full results (snippets, related symbols) are built only for those returned. A whole-file pre-check, cached symbol-name splitting and a per-line substring check keep the full scan fast without changing results. |
| 11 | The file explorer re-rendered every visible row on every keystroke in the editor (row components were memoized, but received new callbacks each render). | New test: 3 keystrokes with 400 visible files caused 1,200 row renders. | Stable callbacks: 1 row render (the file that became dirty). |

## Audit: checked and left unchanged

| Area | Finding |
| --- | --- |
| Ownership | Every user-data service goes through `ProjectService.get` (404 for other users' projects; cross-user attempts are audit-logged). Agent actions are looked up by id **and** user. Semantic queries filter by `project_id`. Workflow C (below) re-verified this end to end. |
| Agent safety | WRITE is not in the model's permission set; identical repeated calls are denied; step, time, context, proposal and consecutive-failure limits end runs safely; tool output is bounded per tool; no hidden reasoning is requested or stored. |
| Proposals | Applied only by explicit approval, after re-checking ownership, project writability, path, content hash, and each change's original text; bounded size. |
| Timeouts | AI provider and embedding calls have timeouts; the frontend API client has a default timeout and honors cancellation; the proxy's read timeouts exceed the backend's. |
| Cancellation | Live analysis is debounced and drops late responses; search and agent requests abort the previous request; health polling aborts in-flight checks. |
| Caches | Project index LRU (32 projects/process), query-embedding LRU (256), limiter key cap (100,000): all bounded. |
| Scanning | Dependency/build/VCS folders, virtual environments, secret files, symbolic links and junctions are skipped; file count and size are capped. The benchmark verifies none of these are stored. |
| Response models | Errors share one `ErrorResponse` shape with a request id; no stack traces are returned. |

## End-to-end workflows

| Workflow | How it was run | Result |
| --- | --- | --- |
| A. Normal coding (login, open project/file, edit, diagnostics, search, explain, fix, reject, new proposal, approve, file changed, diagnostics re-run) | `backend/tests/db/test_module16_workflows.py::test_workflow_a_normal_coding`: real app and PostgreSQL over HTTP, AI steps with the **test-only stub model** (no AI credential exists). | Passes |
| B. Project intelligence | Chrome against the real backend (container), PostgreSQL and the production frontend build, with a 2,002-file linked folder. Semantic search needs an embedding key: verified with the stub embedder in tests only. | Project page renders the full tree (2,004 items) with per-file symbol counts; structure, symbol search and project search work; after fix #10 the defining file ranks first (`func_1500_3` -> `pkg/mod1500.py`). |
| C. Security between users (see, search in every mode, semantic context, index, agent, modify, approve/reject) | `test_workflow_c_security_between_users` (real app and database; stub model/embedder). | Passes: every cross-user request is 404 and nothing changes |
| D. AI disabled | Chrome with AI genuinely unconfigured, plus existing API tests. | The agent panel states "Agent unavailable: AI assistance is turned off (set CODEWALK_AI_ENABLED=true to enable it)."; editor, live diagnostics (Ruff F823 on `app/broken.py:3:9`), search and the explorer keep working. |
| E. Large project | `scripts/system_benchmark.py` (2,000 files, real scanner, index, search, RAG with the stub embedder, agent with the stub model) and Chrome. | `node_modules`, `.git` and `.env` were skipped; in the browser the file list (2,002 files) loaded in 70 ms, opening a file 17 ms, live analysis 34 ms, one Monaco instance, 24 MB JS heap. Found and fixed #10. Numbers: performance report. |

Real AI and embedding providers were not exercised: no credentials are configured, and the
live-provider tests were skipped (not passed).
