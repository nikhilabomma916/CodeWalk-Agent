# Security audit (Module 21)

Audit of the code on `feature/security-hardening` (Modules 1-20), with the threat model, what was
checked and how, the findings, and the remaining risks. "Verified" means checked by an automated
test that runs in the regression suite, or by a direct probe recorded here.

## Threat model

| Actor | Goal | Main defenses |
| --- | --- | --- |
| Anonymous attacker | read or change data, guess passwords | session required on every non-public route (swept automatically), Argon2id, shared login limits, origin check, CORS allow-list |
| Malicious signed-in user | reach another user's projects (IDOR) | ownership check on every project/file/analysis/run/action route → 404 (swept automatically) |
| Malicious project / repository | path tricks, symlinks, oversized files, credentials, deceptive names | path validation, no symlink following, size/count limits, credentials never stored, Unicode format characters refused |
| Prompt injection in project files | make the AI act or leak | project text is escaped data; tools, permissions and writes are enforced server-side; changes need approval |
| AI / API abuse | cost or availability | per-user limits shared across instances, prompt-size limit, timeouts, no automatic retries |
| Proposal replay / concurrent approval | apply stale or duplicated changes | stale-patch checks, single pending → applied transition, concurrency tests |
| Stolen provider or GitHub credentials | use keys elsewhere | keys server-side only (`SecretStr`), never logged or returned; GitHub tokens encrypted at rest, bound to the user, revocable |

## What was checked

| Area | Result | Evidence |
| --- | --- | --- |
| Secrets in the repository and history | none (only deliberate fake fixtures in tests) | pattern scan of tracked files and full history (keys, tokens, private keys); no tracked `.env`/key files |
| Authentication | Argon2id, hashed session tokens, new token per login, expiry, server-side logout, uniform failure for unknown emails | `tests/db/test_auth_api.py` |
| Authentication on every route | every non-public operation answers 401 anonymously | `test_every_non_public_operation_requires_a_session` (OpenAPI sweep) |
| Cross-user access | every project/file/analysis-scoped operation answers 404/422 to another user, reveals nothing, changes nothing | `test_no_operation_reveals_or_changes_another_users_project` (OpenAPI sweep), `test_ownership_api.py` |
| Cookies / CSRF / CORS | HttpOnly, SameSite=Lax, Secure in production; origin check on state-changing requests; no wildcard origins | `test_security_api.py`, `test_hosting_runtime.py` |
| Security headers | API: CSP `default-src 'none'`, nosniff, frame DENY, no-referrer, COOP, `Cache-Control: no-store`, HSTS in production. Frontend: nonce CSP | probe; `test_security_api.py`; frontend `csp` tests |
| Request logging | path template only (no query strings: OAuth codes are never logged); nginx logs `$uri`; httpx at WARNING | `app/core/middleware.py`, `deploy/nginx/codewalk/http-context.conf` |
| Proxy headers | nginx overwrites `X-Forwarded-For` (no spoofing behind the proxy); Vercel sets it itself | `deploy/nginx/codewalk/proxy-headers.conf` |
| Paths | traversal, absolute, drive, UNC, NUL and control characters refused or normalized; **deceptive Unicode accepted (fixed, F1)** | `tests/test_security_units.py`, `test_deceptive_file_paths_are_refused` |
| Execution | no shell, `eval`/`exec`, pickle or unsafe YAML; subprocesses (ruff, Node) use fixed arguments with code on stdin | code sweep |
| SQL | ORM/Core expressions everywhere; the only raw statements are constants | code sweep |
| Uploads / imports | body limits, per-file and count limits, credentials and dependency folders skipped, archive links never followed | upload and GitHub tests |
| Rate limits | **per process only (fixed, F2)**; **no per-account login limit (fixed, F3)** | `test_login_limit_is_shared_by_every_instance`, `test_account_limit_applies_across_addresses` |
| AI providers | one explicit provider, own key only, keys never in prompts, logs or responses | `tests/test_ai_providers_multi.py` |
| GitHub OAuth | state bound to user, single-use; tokens AES-GCM; read scopes only | `tests/db/test_github_api.py` |
| Agent | read-only tool allowlist per mode, tool-call and proposal budgets, loop limits, read-only on uploads | `tests/db/test_agent_api.py`, `test_module17_*` |

## Findings and fixes

| Id | Severity | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| F1 | Medium | File paths and project names accepted invisible/direction-changing Unicode (U+202E right-to-left override, zero-width spaces, line separators, C1 controls) and segments with leading/trailing spaces: a file could display as another in the tree, diffs and proposals ("Trojan Source"-style spoofing) | refused at validation; imports skip such files as `invalid_path` | `test_security_units.py`, `test_deceptive_file_paths_are_refused` |
| F2 | High (for multi-instance hosting) | Login, registration, AI, agent, retrieval and import limits were held in each process: on Vercel each instance (and each cold start) had its own counters, multiplying the allowed attempts | `DatabaseAttemptLimiter`: one shared sliding window in PostgreSQL (`rate_limit_events`, hashed keys, per-key advisory lock); falls back to the process limit if the database is unreachable | `test_login_limit_is_shared_by_every_instance`, fallback unit test |
| F3 | Medium | Sign-in attempts were limited per address + email only: guessing one account's password from many addresses was not throttled | per-account limit (`CODEWALK_LOGIN_ACCOUNT_MAX_ATTEMPTS`, default 50 per window; higher than the per-address limit so a real user is not easily locked out) | `test_account_limit_applies_across_addresses` |

Migration `f3c7d1e9a2b4` (additive): table `rate_limit_events`.

## Remaining risks (not fixed here)

- **Account lockout by a determined attacker**: 50 failed attempts in 15 minutes from anywhere block
  sign-in to that account for the rest of the window. A CAPTCHA or e-mail verification would be the
  next step; consider a Vercel Firewall rule on `/api/v1/auth/*` as well.
- **No e-mail verification or password reset**: accounts are not verified; a lost password cannot be
  recovered by the user.
- **`repo` scope**: when private repositories are enabled, GitHub grants write access with the token.
- **Live providers and GitHub** were exercised only through mocks (no credentials available).
- **Prompt injection** cannot be eliminated, only contained: the model may still give a wrong
  *answer* based on injected text; it cannot act on it.
