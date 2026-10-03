# Module 14 test report — Testing, QA & Production Validation

Branch `feature/testing-qa-production-validation` (from `develop` at `df93311`, Modules 1–13).
Validation date: 2026-10-03. Every count below comes from a run on that date; nothing is
estimated. Status values: **PASS**, **FAIL**, **SKIPPED** (did not run, reason given), **NOT RUN**,
**OPTIONAL LIVE TEST** (runs only with provider credentials).

## 1. Environment

| Item | Value |
| --- | --- |
| Host | Windows 11 (10.0.26200), 8 logical CPUs, Docker Desktop (WSL2), Node 26 |
| Backend tests | `codewalk-backend-test:local` (Linux, Python 3.12, uv 0.12.17, Node 22) on the compose network. psycopg cannot load on this host (Windows Application Control), so every database-backed step runs in Linux containers |
| Database | `pgvector/pgvector:pg17-bookworm` (PostgreSQL 17.11, pgvector 0.8.7); tests use `codewalk_test`, the live stack uses `codewalk` (the development database was kept) |
| Frontend | Next.js dev server on the host, Chrome (real UI interaction through Claude in Chrome) |
| Providers | no Anthropic or Voyage key configured |

## 2. Regression command

`npm run test:all:docker` (`node scripts/test-all.mjs --backend-docker`; `scripts/test-all.ps1`
wraps it for Windows PowerShell). It runs the runner self-test first, then the backend (ruff, ruff
format, mypy, pytest, `alembic upgrade head`, `alembic check`) and the frontend (lint, format
check, typecheck, vitest, production build), and exits non-zero if any step fails. Commands are
started without a shell (npm on Windows excepted, with shell-safe arguments), the database
password reaches them only through environment variables, and all output is redacted.

## 3. Results by area

Final run: `node scripts/test-all.mjs --backend-docker` — exit code 0, all 14 steps PASS.

| Area | Command / scope | Result | Status |
| --- | --- | --- | --- |
| Regression runner self-test | `scripts/runner.test.mjs` | 9 passed, 0 failed | PASS |
| Backend lint / format / types | ruff, ruff format --check, mypy --strict | clean | PASS |
| Backend tests (unit, API, PostgreSQL + pgvector) | `pytest` in the Linux container | 433 passed, 3 skipped, 0 failed | PASS |
| — security subset | auth, ownership (26 endpoint sweep), paths, secret files, agent tools, prompt injection, concurrency (`npm run test:security`) | included in the 433 | PASS |
| — agent | `test_agent_unit.py`, `db/test_agent_api.py` (stub model, incl. malicious) | included in the 433 | PASS |
| — RAG | chunking, provider (mock transport), indexing/search/fallback on pgvector (stub embedder) | included in the 433 | PASS |
| — proposed changes | approve / reject / stale / duplicate / 8 simultaneous approvals | included in the 433 | PASS |
| Live provider tests | `test_live_ai_provider.py`, `test_live_voyage.py`, `db/test_live_agent.py` | not executed: no credentials | OPTIONAL LIVE TEST (3 SKIPPED) |
| Migrations | `alembic upgrade head`, `alembic check` | head `7b3e1c9d4f62`, no drift | PASS |
| Frontend lint / format / types | eslint, prettier --check, tsc | clean | PASS |
| Frontend tests | vitest, 21 files | 181 passed (181) | PASS |
| Frontend production build | `next build` | built | PASS |
| Live stack | `npm run test:integration` against the running backend container, `codewalk` database and Next.js dev server | 12 passed; 68 requests in the backend access log during the run | PASS |
| Performance | `npm run test:perf` (Parts A and B) | measured, see section 6 | PASS (measurements recorded) |
| Browser E2E | Chrome, real interaction | 7 PASS, 1 NOT RUN (B-06) | PASS / NOT RUN |
| Secret scan | live DB password + credential patterns over 364 repository files and all run logs | password found nowhere; 7 pattern hits, all deliberate fakes or placeholders (test fixtures, CI throwaway password) | PASS |

Skipped tests (reasons printed by `pytest -ra`): the three live-provider tests above. Skipped is not
counted as passed.

## 4. Bugs found and fixed

| ID | Bug | Root cause | Fix | Regression test |
| --- | --- | --- | --- | --- |
| F1 | Credential files (`.aws/credentials`, `.kube/config`, `.ssh/*`, `credentials.json`, `*.tfstate`, …) could be stored, searched, sent to the agent and the embedding provider | secret check matched file names only | path-aware `is_secret_path()` used by storage validation, the search index and the folder scanner | `tests/db/test_secret_paths_api.py` (16), `test_project_intelligence.py` — 15/15 failed before the fix |
| F2 | Eight simultaneous approvals of one proposal all applied (all 200) | check-then-act without a lock | `SELECT … FOR UPDATE` on the action row | `test_simultaneous_approvals_apply_a_proposal_once` |
| F3 | The first regression runner split a quoted Docker command through the Windows shell, ran `env` instead of pytest, printed the database password, and reported PASS; a nested `node --test` also passed on failure (`NODE_TEST_CONTEXT`) | shell parsing; inherited environment | runner rewritten (`scripts/lib/runner.mjs`); log deleted; development password rotated and removed from tracked files | `scripts/runner.test.mjs` (9) |
| F4 | Clicking a search result while no file was open opened the file at line 1 instead of the result's line (Module 9) | the reveal request was consumed before Monaco mounted | pending reveal applied on mount (nonce-tracked) | `features/editor/monaco-editor.test.tsx`; browser B-04 |
| F5 | `.gitignore` rule `lib/` (Python packaging) silently excluded `scripts/lib/runner.mjs` from version control | over-broad ignore rule | `!scripts/lib/` exception | verified from a clean clone of the commit |

Details of F1–F3: `security-validation.md`.

## 5. Browser end-to-end (real interaction)

Chrome was foregrounded and a real click was confirmed to register before any check; results are
from UI interaction, not screenshots alone. Two throw-away accounts were created on the local
stack (browser autofill had to be overridden).

| ID | Scenario | Status |
| --- | --- | --- |
| B-01 | Register, log in | PASS |
| B-02 | Create project and file, type code, error marker + Problems entry | PASS |
| B-03 | Explain error with AI unavailable: message shown, code unchanged | PASS |
| B-04 | Search result opens the closed file at the result's line (Ln 4 Col 18) | PASS (after F4) |
| B-05 | Agent panel: context shown, Ask disabled with reason | PASS |
| B-06 | Agent proposal review / reject / approve in the UI | NOT RUN (no AI key; the same flow is covered by `agent.test.tsx` and `test_agent_api.py` with the stub model) |
| B-07 | User B opens user A's project URL: "Project not found", nothing leaked, API 404 | PASS |
| B-08 | Sign out: `/auth/me` 401, `/app/coding` redirects to `/login?next=…` | PASS |

## 6. Performance

See `performance-report.md` (real measurements at 10, 100 and 500 files, concurrency, large
files; setup time separated). Highlights: symbol search p50 12 / 30 / 43 ms; project scan 17 / 57 /
248 ms; 200 concurrent searches at 28.5 requests/s; oversized input refused with 413 in 39 ms.
Indexing inserts one row per chunk (1,021 statements for 2,999 chunks) — the main bottleneck.

## 7. Migrations

`alembic upgrade head` → head `7b3e1c9d4f62`; `alembic check` reports no drift; the downgrade /
upgrade round trip passes; a database populated at the pre-RAG revision `aa335eec9810` upgrades
with its data intact (`test_production_validation.py`).

## 8. Skipped, not run, optional

| Item | Status | Reason |
| --- | --- | --- |
| `test_live_ai_provider.py`, `test_live_voyage.py`, `db/test_live_agent.py` | OPTIONAL LIVE TEST (SKIPPED) | no provider credentials; the unavailable-provider behavior is tested separately (unit, DB and live suites) |
| B-06 | NOT RUN | needs an AI provider key |
| Symlink scanner cases | run in Linux containers / CI only | creating symlinks needs elevated rights on Windows |
| Real provider latency, frontend rendering performance | NOT RUN | no credentials; out of scope for the functional checks |

## 9. Limitations

- Rate limits are per backend process.
- The frontend has no Content-Security-Policy yet (deployment configuration).
- Agent cancellation stops the browser waiting; the server finishes the run within its limits.
- The former default development password remains in earlier commits (it is no longer accepted).
- Browser checks are manual (Claude in Chrome), not an automated Playwright suite.

## 10. Reports

`module-14-test-matrix.md` (45 automated rows + 8 browser rows), `security-validation.md`,
`performance-report.md`.
