# Module 14 QA test matrix

Status values: **PASS** (the automated test or the recorded manual check passed in the Module 14
final validation), **FAIL**, **SKIPPED** (did not run, reason given), **NOT RUN**, **OPTIONAL LIVE
TEST** (runs only with provider credentials). "Actual Result" states what was observed, not what
was hoped for. Test type: U = unit, A = API (FastAPI test client), DB = API on real PostgreSQL +
pgvector, L = live stack over HTTP, B = browser, P = performance, F = frontend component.
Test files are under `backend/tests/` (backend), `frontend/` (F), `tests/integration/` (L).

| ID | Area | Scenario | Precondition | Action | Expected Result | Actual Result | Status | Test Type | Priority |
|---|---|---|---|---|---|---|---|---|---|
| M14-001 | Analysis | Every language analyzer reports located diagnostics | — | `test_analysis_engine.py`, `test_analysis_api.py` | line/column/severity/rule/source set for Python, TS/JS, JSON, HTML, CSS, SQL, Markdown, YAML, Java/C/C++ | as expected | PASS | U/A | High |
| M14-002 | Analysis | Malformed, empty, oversized, unsupported source | — | analysis API with each input | diagnostics for malformed; empty ok; >2 MB → 413; unsupported → capability "not supported" | as expected (413 in 39 ms for 2.3 MB) | PASS | U/A/P | High |
| M14-003 | Analysis | Malformed fixture project analyzed, no crash | malformed project stored | analyze each file (`test_fixture_projects_api.py`) | 201 with ≥1 diagnostic per file | as expected | PASS | DB | High |
| M14-004 | Intelligence | Symbols, imports, relationships, statistics | import-chain project | `POST /analyze` | routes→service→repo→db edges; symbol counts | as expected | PASS | DB | High |
| M14-005 | Intelligence | Scanner skips ignored, binary, secret, symlinked files | workspace folder | `test_project_intelligence.py` | skipped with reasons; secrets/credential folders never read | as expected (symlink cases: Linux only) | PASS | U | High |
| M14-006 | Persistence | Project/file CRUD, versions, history caps | signed in | `test_projects_files_api.py`, `test_repositories.py` | CRUD works; versions numbered; history pruned | as expected | PASS | DB | High |
| M14-007 | Persistence | Parallel saves to one file | 8 sessions | `test_concurrency_api.py` | no 500; versions unique and gap-free | as expected | PASS | DB | High |
| M14-008 | Database | Upgrade a populated pre-RAG database | data at `aa335eec9810` | `alembic upgrade head` | data kept; pgvector, chunks, agent tables present | as expected | PASS | DB | High |
| M14-009 | Database | Downgrade/upgrade round trip, no drift | — | `test_migrations.py`, `alembic check` | round trip ok; "No new upgrade operations" | head `7b3e1c9d4f62`, no drift | PASS | DB | High |
| M14-010 | Database | Deleting a user removes all owned rows | user with projects, files, RAG, agent data | delete user | 0 rows in 10 owned tables; other users untouched | as expected | PASS | DB | High |
| M14-011 | Auth | Register, login, logout, duplicate, weak password | — | `test_auth_api.py` | correct codes; no password in responses or logs | as expected | PASS | DB | High |
| M14-012 | Auth | Forged, expired, disabled sessions; cookie flags | — | `test_auth_api.py` | 401/403; httpOnly, SameSite, Secure when configured | as expected | PASS | DB | High |
| M14-013 | Auth | Protected frontend routes | signed out | open `/app/*` | redirect to `/login?next=…` | redirect observed in browser (B-08) | PASS | F/B | High |
| M14-014 | Authorization | Another user on every project-scoped endpoint (26) | user A project | `test_security_api.py` | 404, no content; anonymous 401; no AI call | as expected | PASS | DB | Critical |
| M14-015 | Authorization | IDOR on file, analysis, history, run, proposal ids | user A objects | B requests A's ids | 404 everywhere | as expected | PASS | DB/L | Critical |
| M14-016 | Paths | Traversal, absolute, UNC, backslash, NUL, encoded | — | create/snippet/context/rename with each path | 422 (encoded forms stored only as literal names) | as expected | PASS | DB | Critical |
| M14-017 | Secrets | Credential paths and names refused | — | `test_secret_paths_api.py` (15 cases) | 422; never searchable; legacy rows invisible | **failed before fix (F1)**, passes after | PASS (fixed) | DB | Critical |
| M14-018 | Search | Exact, prefix, token, path, text, filters, limits | indexed project | `test_search_api.py`, `test_search_ranking.py` | ranked, filtered, bounded results | as expected | PASS | U/DB | High |
| M14-019 | Search | Newest query wins when an older request answers last | — | `project-search.test.tsx` race test | newest results stay | as expected | PASS | F | Medium |
| M14-020 | Search | Result opens file at its line when no file is open | no editor open | `monaco-editor.test.tsx` | caret at result line | **failed before fix**, passes after | PASS (fixed) | F | Medium |
| M14-021 | RAG | Chunking, hashing, RRF, provider errors, dimensions | — | `test_retrieval_chunking.py`, `test_retrieval_provider.py` | as specified | as expected | PASS | U | High |
| M14-022 | RAG | Index, incremental reuse, stale exclusion, ownership | stub embedder | `test_retrieval_api.py` | correct chunks; reuse; no stale or foreign results | as expected | PASS | DB | High |
| M14-023 | RAG | Unavailable provider → deterministic fallback | no key | hybrid search | `mode_used: deterministic` + warning; no fake scores | as expected (also live) | PASS | DB/L | High |
| M14-024 | RAG | Database failure in vector query | broken query vectors | hybrid search, AI explain | fallback; request transaction intact | as expected | PASS | DB | High |
| M14-025 | AI | Unavailable, timeout, malformed, refusal, rate limit | stub provider | `test_ai_api.py`, `test_ai_provider.py` | normalized error codes; no fake output | as expected | PASS | U/DB | High |
| M14-026 | Agent | Tool loop, events, persistence, history | stub model | `test_agent_api.py` | completed run; metadata stored; no reasoning | as expected | PASS | DB | High |
| M14-027 | Agent | Unknown tool, invalid args, traversal, secret and ignored files | stub model acting maliciously | `test_agent_api.py` | denied/errored; nothing written | as expected | PASS | DB | Critical |
| M14-028 | Agent | Repeated calls, loop detection, step/time/context limits | stub model | `test_agent_api.py`, `test_agent_unit.py` | `limit_reached`, never infinite | as expected | PASS | U/DB | High |
| M14-029 | Agent | WRITE never callable by the model | — | `test_agent_unit.py` | `permission_denied` / no write tool | as expected | PASS | U | Critical |
| M14-030 | Prompt injection | Six injected instructions across README, code, config, retrieval | malicious fixture project | `test_fixture_projects_api.py` | policy unchanged; data escaped; hostile calls contained; change only proposed | as expected | PASS | DB | Critical |
| M14-031 | Proposals | Approve applies once, re-analyzes, records history | pending proposal | approve | file saved as new version; diagnostics returned | as expected | PASS | DB | Critical |
| M14-032 | Proposals | Reject, duplicate, stale, deleted file, invalid edits | pending proposal | each case | rejected unchanged; 409 duplicates/stale; 404 deleted | as expected | PASS | DB | Critical |
| M14-033 | Proposals | 8 simultaneous approvals | pending proposal | parallel approve | exactly one 200, rest 409 | **failed before fix (F2)**, passes after | PASS (fixed) | DB | Critical |
| M14-034 | Proposals | Unauthorized approve/reject | user B | approve A's proposal | 404; proposal stays pending | as expected | PASS | DB | Critical |
| M14-035 | Rate limits | Login, register, AI, agent, RAG limits; per-user isolation | low limits | exceed limit | 429 + Retry-After; other users unaffected | as expected | PASS | U/DB | Medium |
| M14-036 | HTTP | CORS, origin check, headers, body limit | — | `test_config.py`, live suite | CSP, no-store, nosniff, DENY; 403 foreign origin; 413 | as expected (also live) | PASS | A/L | High |
| M14-037 | Config | Production refuses insecure settings | production env | build settings | errors for weak key, http origins, insecure cookie | as expected | PASS | U | High |
| M14-038 | Frontend | Agent panel states: unavailable, loading, answer, proposals, errors (9 kinds), cancel | fake backend | `agent.test.tsx` | correct state; never stuck; no stack trace | as expected | PASS | F | High |
| M14-039 | Frontend | Older agent run cannot overwrite a newer one; a cancelled run frees the panel | fake backend honoring abort | 2 race tests in `agent.test.tsx` | newest answer stays; late answer of a cancelled run never shown | first version **flaked on GitHub CI** (fake fetch ignored abort; timing-dependent), rewritten timing-independent; fails when the run-token guard is removed | PASS (fixed) | F | Medium |
| M14-040 | Frontend | Diff review applies only on Apply; unsaved edits block Apply | fake backend | `agent.test.tsx` | buffer unchanged until Apply | as expected | PASS | F | Critical |
| M14-041 | Live stack | Health, auth, project workflow, isolation, paths, headers | running stack | `tests/integration` (12 tests) | all pass against real backend + DB | 12 passed; DB rows grew as expected | PASS | L | High |
| M14-042 | Live stack | AI / agent / RAG real unavailable state | no keys | live suite | 503 `ai_disabled`; deterministic fallback | as expected | PASS | L | High |
| M14-043 | Performance | 10 / 100 / 500-file projects, concurrency, large files | running stack | `npm run test:perf` | measurements recorded | see performance report | PASS | P | Medium |
| M14-044 | Regression runner | Fails on failure, quotes intact, secrets redacted | — | `scripts/runner.test.mjs` | 9 tests pass | **false PASS + leak found (F3)**, fixed; 9 passed | PASS (fixed) | U | Critical |
| M14-045 | Live providers | Real Anthropic, Voyage, and agent smoke tests | credentials | `test_live_*` | real responses parsed | not executed: no credentials | OPTIONAL LIVE TEST | L | Medium |
| B-01 | Browser | Register, log in | stack running | UI | signed in | signed in; /auth/me returned the new user | PASS | B | High |
| B-02 | Browser | Create project and file, type code, introduce an error | signed in | UI | Monaco marker + Problems entry | Monaco error marker and Problems entry appeared after typing invalid code | PASS | B | High |
| B-03 | Browser | Explain error with AI unavailable | problem selected | Explain | "AI unavailable" message, code unchanged | "AI unavailable" message shown; editor content unchanged | PASS | B | High |
| B-04 | Browser | Search and open a result | file closed | search, click result | file opens at the result's line | result opened billing/cart.py at the result line (caret Ln 4 Col 18) | PASS | B | High |
| B-05 | Browser | Agent panel context and unavailable state | AI off | open Agent | context shown; Ask disabled with reason | context shown; Ask disabled with the unavailable reason | PASS | B | High |
| B-06 | Browser | Agent proposal review, reject, approve | AI configured | UI | per spec | not executed: no AI provider key configured | NOT RUN | B | High |
| B-07 | Browser | User B cannot open user A's project | two users | open A's project URL as B | "Project not found" | "Project not found" shown, no project name or file leaked; API 404 | PASS | B | Critical |
| B-08 | Browser | Logout and protected routes | signed in | sign out, open `/app/coding` | redirect to login | signed out; /auth/me 401; /app/coding redirected to /login?next=%2Fapp%2Fcoding | PASS | B | High |
