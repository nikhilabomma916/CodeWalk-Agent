# API reference (v1)

Base path: `/api/v1`. Interactive documentation is served at `/docs` (Swagger UI) and `/redoc`
in non-production environments. The machine-readable schema is at `/api/v1/openapi.json`.

Every response includes an `X-Request-ID` header. Clients may send their own `X-Request-ID`
(8–128 characters from `[A-Za-z0-9._-]`). Otherwise the server generates one.

## Endpoints

### `GET /api/v1/health`

Full health report. Returns **200** when the status is `ok` or `degraded`, and **503** when a required
dependency check fails (`unavailable`). The body has the same shape in both cases.

```json
{
  "status": "ok",
  "service": "CodeWalk Agent API",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-09-30T17:10:22.094998Z",
  "uptime_seconds": 5.172,
  "checks": []
}
```

`checks` lists only dependencies whose checks are actually registered. Each entry has `name`,
`status` (`pass` \| `fail`), `required`, `latency_ms`, and an optional client-safe `detail`.

### `GET /api/v1/health/live`

Liveness probe. Runs no dependency checks. Returns `{"status": "ok"}`.

### `GET /api/v1/health/ready`

Readiness probe. Same body and status codes as `/health`.

### `GET /api/v1/info`

Public API metadata: `name`, `version`, `api_version`, `environment`, and `docs_url` (`null` when
docs are disabled).

When `CODEWALK_DATABASE_URL` is set, `checks` contains a `database` check (`required: false`). If the
database is unreachable, the status is `degraded` (HTTP 200), because code analysis still works.

## Code analysis

### `POST /api/v1/analysis/code`

Deterministic static analysis for the editor's live diagnostics. The code is parsed and linted, **never
executed**, and **nothing is stored**.

```json
{ "code": "import os\n", "language": "python", "file_path": "src/app.py" }
```

`language` is optional. When it is omitted or `unknown`, it is detected from `file_path`. The response is an
`AnalysisResult`: `language`, `success`, `diagnostics[]`, `capabilities[]` (which kinds of analysis ran,
or why they did not), `analyzers[]` (name + version), `errors[]`, `analysis_duration_ms`, `analyzed_at`,
`metadata`. Each `Diagnostic` has `severity` (`error|warning|information|suggestion`), `category`
(`syntax|lint|style|type|semantic`), `message`, `source`, `code`, 1-based `line`/`column`/`end_line`/
`end_column`, `suggestion`, `documentation_url`, and `fixable`. Source larger than
`CODEWALK_MAX_SOURCE_BYTES` returns 413 `source_too_large`.

| Language | Analyzer |
| --- | --- |
| Python | `ast.parse` (syntax) + Ruff subprocess (pyflakes, pycodestyle errors, bugbear) |
| TypeScript / TSX | TypeScript compiler worker (syntax, types, unused/unreachable code) |
| JavaScript / JSX | TypeScript compiler worker (syntax, redeclarations, unused/unreachable code; no type checking) |
| JSON | strict parser + duplicate keys |
| HTML | structure checks (unclosed/mismatched tags, duplicate ids, …) |
| Java, C, C++, CSS | tree-sitter syntax errors |
| SQL | sqlglot parse errors |
| Markdown | heading and fence checks |

### `GET /api/v1/analysis/languages`

Languages that have analyzers, with `available: false` and a `detail` when tooling is missing (for
example, Node.js is not installed for the TypeScript worker).

## Authentication

The API uses a server-side session. A successful `register` or `login` sets an `httpOnly`,
`SameSite=Lax` cookie (`codewalk_session`, `Secure` in production) holding a random 256-bit token.
Only its SHA-256 is stored. Browsers must send requests with credentials
(`fetch(..., { credentials: "include" })`). The token never appears in a response body.

| Method & path | Description |
| --- | --- |
| `POST /auth/register` | `{name, email, password}` → 201 user + cookie. 409 `email_taken`. 429 `too_many_attempts` |
| `POST /auth/login` | `{email, password}` → 200 user + cookie. 401 `invalid_credentials`, 403 `account_disabled`, 429 `too_many_attempts` (with `Retry-After`) |
| `POST /auth/logout` | ends the session and clears the cookie (204, also when not signed in) |
| `GET /auth/me` | the signed-in user, or 401 `not_authenticated` |

The user object is `{id, name, email, created_at, last_login_at}`. Password hashes are never returned.

- **Email** is trimmed and lower-cased. **Passwords** are 8–128 characters, with at least one letter
  and one digit or symbol. They may not be overly repetitive, and may not equal the email address.
- An unknown email and a wrong password produce the same 401 and take the same time. A disabled account
  is only reported after the correct password. Registration has to report a taken email; it is rate
  limited instead.
- **CSRF:** besides `SameSite=Lax`, state-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) that
  carry an `Origin` header must come from `CODEWALK_CORS_ORIGINS` (or the API's own origin).
  Otherwise the response is 403 `origin_not_allowed`.

## Persistence (requires PostgreSQL and a signed-in user)

Every endpoint below requires a session (401 `not_authenticated` otherwise). It returns 503
`database_not_configured` when `CODEWALK_DATABASE_URL` is unset, and 503 `database_unavailable` when
the server cannot be reached. IDs are UUIDs. List endpoints accept `limit`/`offset` and return
`{items, total, limit, offset}`.

**Ownership:** every project belongs to the user who created it. A project, file, analysis, version,
or history entry of another user is answered exactly like a missing one (404), so IDs reveal nothing.
`POST /analysis/code` and the health/info endpoints stay public. Live analysis stores nothing.

### Projects

| Method & path | Description |
| --- | --- |
| `GET /projects/workspace` | server folders under `CODEWALK_WORKSPACE_ROOT` that can be linked |
| `POST /projects` | create `{name, description?, root_path?}`. Names are unique per user, case-insensitively (409 `project_exists`), and may not contain slashes |
| `GET /projects` | the caller's projects, most recently updated first |
| `GET /projects/{id}` | get one |
| `PATCH /projects/{id}` | rename / re-describe |
| `DELETE /projects/{id}` | delete, with its files, analyses and diagnostics (cascade) |
| `POST /projects/{id}/analyze` | run project intelligence; linked folders are rescanned and synced first |
| `GET /projects/{id}/intelligence` | latest intelligence from stored files (404 `not_analyzed` before the first run) |
| `GET /projects/{id}/analyses` | analysis history; filter with `analysis_type` and `file_id` |

Project responses include `stats`: `{file_count, total_bytes, total_lines, languages: [{language,
files}], last_analyzed_at}`. These are computed from the stored files and analyses.

A project with `root_path` is linked to a folder inside `CODEWALK_WORKSPACE_ROOT`. It is read-only
through the file API (409 `project_read_only`) and updated by rescanning. Paths that escape the workspace
are rejected (400/422), and missing folders return 404 `folder_not_found`.

`ProjectAnalysisResult` contains `project`, `files[]` (path, language, size, lines, `symbols[]`,
`imports[]`), `directories[]`, `relationships[]` (file → file or external module), `statistics`
(totals, per-language, largest files, symbol counts, internal/external imports), `errors[]` (files that
failed to parse, which does not stop the analysis), `sync` (created/updated/deleted/unchanged), and
`analysis_id`.

### Files

| Method & path | Description |
| --- | --- |
| `POST /projects/{id}/files` | create `{path, content}`. Records a static analysis of the content |
| `GET /projects/{id}/files` | metadata only (no content), ordered by path |
| `GET /projects/{id}/files/{file_id}` | metadata + content |
| `PATCH /projects/{id}/files/{file_id}` | `{content?, path?}`. New content records an analysis |
| `DELETE /projects/{id}/files/{file_id}` | delete (its analysis history is kept, with `file_id` cleared) |
| `POST /projects/{id}/files/{file_id}/analyses` | analyze the stored content now and record it |
| `GET /analyses/{analysis_id}` | a stored analysis with its diagnostics |

Save responses are `{file, analysis}`. Only the newest `CODEWALK_ANALYSIS_HISTORY_PER_FILE` code
analyses are kept per file.

### File versions

Every content change (create, save, restore, and folder rescans) is stored as a numbered version.
Only the newest `CODEWALK_FILE_VERSION_HISTORY_LIMIT` versions are kept per file.

| Method & path | Description |
| --- | --- |
| `GET /projects/{id}/files/{file_id}/versions` | newest first, without content: `{version, size, line_count, content_hash, source, author_id, created_at}` |
| `GET /projects/{id}/files/{file_id}/versions/{n}` | one version with `content` (404 `version_not_found` once pruned) |
| `POST /projects/{id}/files/{file_id}/versions/{n}/restore` | make version *n* current. Saved as a new version and analyzed like a save |

`source` is `create`, `edit`, `restore`, or `scan`.

### History

Events are written in the same transaction as the action itself, so the history contains exactly
what happened. Nothing is inferred afterwards.

| Method & path | Description |
| --- | --- |
| `GET /history` | the caller's events. Filters: `project_id`, `event_type` (repeatable), `order=desc\|asc` (by time), `limit` ≤ 200, `offset` |
| `GET /history/{event_id}` | one event plus context: `project_exists`, `current_project_name`, `current_file_path` (after renames), and `analysis` (`status`, `language`, `duration_ms`, `diagnostic_count`, `severity_counts`) if still kept |

Event types: `project.created`, `project.updated`, `project.deleted`, `project.analyzed`,
`file.created`, `file.updated`, `file.restored`, `file.deleted`, and `file.analyzed`. Each event stores
`project_name` and `file_path` as they were at the time. `project_id`/`file_id`/`analysis_id` become
`null` once the target is deleted (or the analysis is pruned). `details` holds a small summary, such as
`version`, `diagnostic_count`, `analysis_status`, `renamed_from`, `restored_from`, `changed`, or
`statistics`.

Live editor analysis (`POST /analysis/code`) is not stored, so it does not appear in the history.
Neither do local-folder or in-browser projects.

## Errors

All errors share one shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request is invalid.",
    "request_id": "0f3c…",
    "details": [{ "location": ["body", "name"], "message": "String should have at least 1 character", "type": "string_too_short" }]
  }
}
```

| Status | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` / `unsafe_path` | malformed request or rejected path |
| 401 | `not_authenticated`, `invalid_credentials` | no or expired session; wrong email or password |
| 403 | `account_disabled`, `origin_not_allowed` | disabled account; cross-site write |
| 404 | `not_found`, `project_not_found`, `file_not_found`, `analysis_not_found`, `version_not_found`, `history_event_not_found`, `folder_not_found`, `not_analyzed` | unknown route or resource (or another user's) |
| 409 | `email_taken`, `project_exists`, `file_exists`, `project_read_only` | conflicting write |
| 429 | `too_many_attempts` | sign-in or registration rate limit (`Retry-After` header) |
| 413 | `source_too_large`, `content_too_large` | source above `CODEWALK_MAX_SOURCE_BYTES` |
| 422 | `file_not_analyzable` | stored file has no text content (binary or too large) |
| 503 | `database_not_configured`, `database_unavailable` | persistence is off or unreachable (credentials are never returned) |
| 405 | `method_not_allowed` | wrong HTTP method |
| 413 | `payload_too_large` | body exceeds `CODEWALK_MAX_REQUEST_BODY_BYTES` |
| 422 | `validation_error` | body/query failed validation (`details` lists fields; input values are never echoed) |
| 500 | `internal_error` | unexpected failure (details are logged server-side only) |
| 503 | `service_unavailable` | a required dependency is unavailable |
