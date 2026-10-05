# Security validation (Module 14)

Scope: the complete CodeWalk Agent application after Modules 1–13, on branch
`feature/testing-qa-production-validation`. Every statement below is backed by an automated test
that ran in the Module 14 final validation (see the test report for counts), or is marked as a
limitation. Attack strings live in the test files, not here.

## Summary

| Area | Result | Evidence |
| --- | --- | --- |
| Authentication | PASS | `backend/tests/db/test_auth_api.py` (18 tests), `frontend/features/auth/*` |
| Authorization / ownership (IDOR) | PASS | `test_security_api.py` sweep of 26 endpoint/method pairs, `test_ownership_api.py`, `test_agent_api.py`, live `test_live_validation.py` |
| Path traversal and confinement | PASS | `test_paths.py`, `test_security_api.py`, `test_secret_paths_api.py`, agent tool tests |
| Secret files | **FAIL → fixed** (finding F1) | `test_secret_paths_api.py` (15 cases), `test_project_intelligence.py` |
| Prompt injection | PASS | `test_agent_unit.py`, `test_agent_api.py`, `test_fixture_projects_api.py` |
| Agent tool authorization | PASS | `test_agent_unit.py`, `test_agent_api.py` |
| Proposed changes (approve / reject / stale) | **FAIL → fixed** (finding F2) | `test_agent_api.py`, `test_concurrency_api.py` |
| Rate limiting | PASS (process-local) | `test_auth_api.py`, `test_retrieval_provider.py`, `test_agent_api.py`, `test_production_validation.py` |
| Input validation and size limits | PASS | `test_errors.py`, `test_agent_unit.py`, `test_security_api.py` |
| Error handling (no leaks) | PASS | `test_errors.py`, `test_agent_api.py`, frontend `agent.test.tsx` failure states |
| CORS, CSRF, security headers | PASS | `test_config.py`, `test_auth_api.py`, `test_security_api.py`, live suite |
| Secrets in code, logs, and artifacts | **FAIL → fixed** (finding F3) | secret scan, `scripts/runner.test.mjs` |

## Findings

**F1 — credential files could reach the AI and embedding providers (fixed).** The secret-file
rule matched file *names* only, so credentials identified by their folder (`.aws/credentials`,
`.kube/config`, `.docker/config.json`, `.ssh/*`, `.gnupg/*`) and common secret names
(`credentials.json`, `client_secret*.json`, `service-account*.json`, `secrets.{json,yaml,yml}`,
`*.tfstate`, `.pgpass`, `.htpasswd`, `.s3cfg`, `.boto`, `.dockercfg`) could be stored, were
searchable, and could be given to the agent and to the embedding provider. Root cause: no
path-aware check. Fix: `is_secret_path()` in `project_intelligence/scanner.py`, used by path
validation (storage), the search index (search, context, RAG, agent tools), and the folder
scanner (whole credential folders skipped). Regression: 15 API cases plus a legacy-row test
proving rows stored before the fix stay invisible, and a scanner unit test. Reproduced failing
before the fix (15/15), passing after.

**F2 — concurrent approvals applied a proposal several times (fixed).** Eight simultaneous
`approve` requests for one proposal all returned 200. Root cause: check-then-act without a row
lock. Fix: the decision locks the action row (`SELECT … FOR UPDATE`), so exactly one approval
applies and the rest receive `409 action_not_pending`. Regression:
`test_simultaneous_approvals_apply_a_proposal_once` (stable across repeated runs).

**F3 — the regression runner leaked the database password and reported a false PASS (fixed).**
The first version of `scripts/test-all.mjs` ran Docker commands through a Windows shell, which
split the quoted container command; one step ran `env` instead of pytest (printing the
container environment, including the database URL with its password) and exited 0. Actions:
the log was deleted; the development database password was rotated (the leaked value is now
rejected over the network); the documented default password was removed from
`docker-compose.yml`, `.env.example`, and the README (compose now requires
`POSTGRES_PASSWORD` in `.env`); the runner was rewritten (`scripts/lib/runner.mjs`) to run
commands without a shell (npm excepted on Windows, with shell-safe arguments), pass credentials
only through environment variables, redact output, and pass a step only on exit status 0. A
second false-PASS mechanism found while testing the runner (an inherited `NODE_TEST_CONTEXT`
making a nested `node --test` exit 0 on failure) is also fixed. Regression:
`scripts/runner.test.mjs` (9 tests: failing and passing commands and test files, quoting,
secret redaction). Note: the old default value remains in earlier commits of the shared
history; it only ever protected local development databases, and the running one no longer
accepts it.

## Controls verified

- **Authentication**: Argon2id hashes; opaque session token in an `httpOnly`, `SameSite=Lax`
  cookie (`Secure` in production) of which only the SHA-256 is stored; expiry; logout;
  forged, expired, and disabled-account sessions rejected; unknown email and wrong password
  indistinguishable; passwords never in responses or logs.
- **Authorization**: every project-scoped endpoint, plus analyses, history entries, agent runs,
  and proposals, answers another user with `404` and no content, and a signed-out client with
  `401`. Malformed ids are `422`, unknown ids `404`. Cross-user attempts are written to the
  audit log (`security.project_access_denied`).
- **Paths**: `..`, absolute POSIX and Windows paths, UNC paths, backslash variants, and NUL bytes
  are rejected. Percent-encoded forms are accepted only as literal names: paths are database
  values and are never URL-decoded or opened on the host, so they cannot escape. Folder scans
  stay inside `CODEWALK_WORKSPACE_ROOT` and never follow symlinks (symlink tests need elevated
  rights on Windows and run on Linux/CI).
- **Prompt injection**: project text reaches the model only inside escaped data blocks under a
  fixed system policy; a stand-in model that obeys injected instructions is still contained:
  unknown tools denied, paths outside the project rejected, secret files invisible, changes only
  ever proposed, no outbound tool exists, and three blocked calls in a row end the run.
- **Writes**: only `approve` writes, after re-checking ownership, file, path, content hash,
  every original text, and change size; stale proposals are refused; decisions are serialized.
- **HTTP**: CORS allow-list (no wildcard; HTTPS-only in production), origin check on
  state-changing requests, body limit (413), CSP `default-src 'none'`, `Cache-Control: no-store`,
  `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production.
- **Secrets**: provider keys and the database URL are server-side settings; status endpoints
  never return values; the frontend bundle contains no key names; the repository scan finds
  only deliberately fake test values.

## Known limitations

- Rate limits are per process; several backend instances need a shared store or proxy limits.
- The frontend has no Content-Security-Policy yet (Next.js nonces and Monaco workers belong to
  deployment configuration).
- Agent cancellation stops the browser waiting; the server finishes the run within its limits.
- The default development password exists in earlier commits (see F3).
