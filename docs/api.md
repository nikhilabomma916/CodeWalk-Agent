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

## Persistence (requires PostgreSQL)

Every endpoint below returns 503 `database_not_configured` when `CODEWALK_DATABASE_URL` is unset, and
503 `database_unavailable` when the server cannot be reached. IDs are UUIDs. List endpoints accept
`limit`/`offset` and return `{items, total, limit, offset}`.

### Projects

| Method & path | Description |
| --- | --- |
| `GET /projects/workspace` | server folders under `CODEWALK_WORKSPACE_ROOT` that can be linked |
| `POST /projects` | create `{name, description?, root_path?}`. Names are unique, case-insensitively (409 `project_exists`) |
| `GET /projects` | list, most recently updated first |
| `GET /projects/{id}` | get one |
| `PATCH /projects/{id}` | rename / re-describe |
| `DELETE /projects/{id}` | delete, with its files, analyses and diagnostics (cascade) |
| `POST /projects/{id}/analyze` | run project intelligence; linked folders are rescanned and synced first |
| `GET /projects/{id}/intelligence` | latest intelligence from stored files (404 `not_analyzed` before the first run) |
| `GET /projects/{id}/analyses` | analysis history; filter with `analysis_type` and `file_id` |

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
| 404 | `not_found`, `project_not_found`, `file_not_found`, `analysis_not_found`, `folder_not_found`, `not_analyzed` | unknown route or resource |
| 409 | `project_exists`, `file_exists`, `project_read_only` | conflicting write |
| 413 | `source_too_large`, `content_too_large` | source above `CODEWALK_MAX_SOURCE_BYTES` |
| 422 | `file_not_analyzable` | stored file has no text content (binary or too large) |
| 503 | `database_not_configured`, `database_unavailable` | persistence is off or unreachable (credentials are never returned) |
| 405 | `method_not_allowed` | wrong HTTP method |
| 413 | `payload_too_large` | body exceeds `CODEWALK_MAX_REQUEST_BODY_BYTES` |
| 422 | `validation_error` | body/query failed validation (`details` lists fields; input values are never echoed) |
| 500 | `internal_error` | unexpected failure (details are logged server-side only) |
| 503 | `service_unavailable` | a required dependency is unavailable |
