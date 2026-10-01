# Architecture

This document describes the architecture of Batch 1 (Modules 1–3: foundation, editor, API) and Batch 2
(Modules 4–6: code analysis, project intelligence, persistence), and where later modules plug in.

## Layers

```
Frontend (Next.js)
  components/ui        presentational primitives, no business logic
  features/*           feature UI + state (workspace context/reducer, explorer, editor, problems)
  services/api         the only place that performs HTTP; validates every response with zod
        │  HTTP, JSON, /api/v1
Backend (FastAPI)
  api/routes           HTTP concerns only: parse, call a service, return a schema
  api/deps.py          dependency providers (settings, DB session, services)
  services             business logic, framework-agnostic
  repositories         data access over a SQLAlchemy Session; flush, never commit (services own transactions)
  db                   declarative models, engine/session (app/db), Alembic migrations (backend/migrations)
  integrations         external services behind typed, failure-mapped clients
  core                 configuration, logging, exceptions, middleware
```

## Frontend

### State

`features/workspace/state.ts` defines a single reducer that is the source of truth for the project,
file buffers (saved vs. current content), open tabs, the active file, diagnostics, and editor settings.
`WorkspaceProvider` wraps it with async actions (open, save, create) and confirmation prompts.
Cursor position lives in a separate small context so caret movement re-renders only the status bar.

Monaco keeps one text model per open file (content, undo history, markers). Model URIs are namespaced
by a per-project id (`file:///<projectId>/<path>`) so identically named files from different projects
never collide. Models are disposed when their tab closes.

### Project sources

The workspace talks only to the `ProjectSource` interface (`features/workspace/sources/types.ts`):

| Source | Origin | Where Save goes |
| --- | --- | --- |
| `MemoryProjectSource` | "New project" | browser memory (lost on reload) |
| `LocalDirectorySource` | File System Access API (Chromium) | the real file on disk |
| `LocalSnapshotSource` | `<input webkitdirectory>` fallback | browser memory (originals untouched) |
| `ServerProjectSource` | Welcome → "Server projects", or New project → "Server" (PostgreSQL) | `PATCH /projects/{id}/files/{file}` |

Server projects are listed with `use-server-projects.ts`. Folder-linked server projects are read-only in
the editor. Every source applies the same ignore rules
(`lib/project-paths.ts`), skips `.env` files, refuses binary or non-UTF-8 files, and caps file size
and entry count.

### Diagnostics

`types/diagnostics.ts` defines the `Diagnostic` shape: severity, message, file, line, column,
source, code, and suggested action. The shape matches the target backend analysis response. Diagnostics
are stored per *producer* (`state.diagnostics[source][file]`). There are two producers: Monaco's
built-in syntax validation, and the backend analysis engine.

`features/analysis/live-analysis.ts` drives backend analysis for the active file. Each edit restarts a
450 ms debounce timer and aborts the in-flight request. A sequence token also discards any late
response for older content, even if the server ignores the abort. Results become Monaco markers
(`setModelMarkers`) and Problems-panel rows. Clicking a row reveals the location in the editor.

The intelligence panel (`features/intelligence`) runs `POST /projects/{id}/analyze` for server
projects. It shows statistics, per-file symbols and imports, and parse errors. Clicking a symbol
opens the file at its line.

### API client

`services/api/client.ts` wraps `fetch` with timeouts, caller cancellation, and JSON parsing. It
validates responses against zod schemas and maps the backend `ErrorResponse`. Failures surface as
`ApiError` with a `kind` of `network`, `timeout`, `aborted`, `http`, or `malformed`. Nothing is
silently swallowed.

## Backend

### Application factory

`app/application.py:create_app(settings)` builds the app. It configures logging, registers exception
handlers and middleware, stores services on `app.state`, and mounts routers. `app/main.py` exposes
`app = create_app()` for Uvicorn. Tests call the factory with isolated `Settings`.

Middleware order (outermost first): CORS → request context (request id, security headers, access log,
500 fallback) → body-size limit → routes. Handling unexpected errors inside the CORS layer means
browsers can still read 500 responses.

### Error contract

Every error response has the shape `{"error": {"code", "message", "request_id", "details?"}}`.
Validation errors list field locations but never echo submitted values. Unexpected errors are logged
with a stack trace server-side and returned as a generic `internal_error`.

### Health

`HealthService` runs registered `HealthCheck`s concurrently, each with a timeout. Required failures
produce `unavailable` (HTTP 503). Optional failures produce `degraded`. The `database` check (a real
`SELECT 1`) is registered and optional: when PostgreSQL is down the API reports `degraded` and keeps
serving code analysis. The AI provider is absent from the report until its module registers a check.

### Code analysis (Module 4)

`services/analysis/engine.py` resolves the language (explicit or from the file path), runs every
analyzer registered for it in `AnalyzerRegistry`, and normalizes the output into one `AnalysisResult`.
Diagnostics are sorted by position and severity and capped. Analyzers implement the `Analyzer`
protocol (`analyzers/base.py`). A new language needs a new analyzer class and one line in
`AnalysisEngine.create_default`. An analyzer that crashes becomes an entry in `errors` and does not
fail the request. Each result declares its `capabilities`, so clients know whether, for example,
type checking actually ran.

Source code is **never executed**. Python is parsed with `ast.parse` and linted by Ruff via stdin.
TypeScript/JavaScript go to a long-lived Node worker that uses the TypeScript compiler API without
resolving imports or emitting output (`tools/typescript-analyzer`). Other languages use pure parsers
(tree-sitter, sqlglot, the standard library). Every subprocess has a timeout.

### Project intelligence (Module 5)

`services/project_intelligence/`:

- `scanner.py`: recursive scan of a linked folder. It never follows symlinks or junctions, never
  opens secret files (`.env*`, keys), skips dependency/build directories (`node_modules`, `.venv`,
  `dist`, …) and honours nested `.gitignore` files. It caps file count and size, and detects binary
  files.
- `python_structure.py`: symbols (classes, methods, functions, variables) and imports from the AST.
- `javascript_structure.py`: the same for JS/TS/JSX/TSX from tree-sitter parse trees.
- `relationships.py`: resolves imports to project files (Python packages, relative and absolute
  modules; JS relative paths and the nearest tsconfig/jsconfig `baseUrl`/`paths`, with extension and
  `index` resolution). Anything else is marked external.
- `project_analyzer.py`: combines the above into `ProjectAnalysisResult` with statistics. A file
  that fails to parse is reported in `errors` and does not stop the analysis.
- `service.py`: persistence-aware orchestration. It syncs scanned files into the database
  (create/update/delete by content hash) and caches each file's structure in `files.structure`
  keyed by content hash and `STRUCTURE_VERSION`. It records an `analyses` row of type
  `project_intelligence`.

### Persistence (Module 6)

PostgreSQL 17 via SQLAlchemy 2 (sync, psycopg 3) and Alembic. Request flow: route → service
(business rules, transaction boundary) → repository (queries, `flush` only) → session.

| Table | Key columns | Notes |
| --- | --- | --- |
| `projects` | `id` UUID, `name`, `description`, `root_path`, timestamps | unique index on `lower(name)` |
| `files` | `id`, `project_id` → projects (CASCADE), `path`, `language`, `content`, `size`, `line_count`, `content_hash`, `structure` JSONB, timestamps | unique `(project_id, path)` |
| `analyses` | `id`, `project_id` (CASCADE), `file_id` (SET NULL), `analysis_type`, `status`, `duration_ms`, `diagnostic_count`, `details` JSONB, `created_at` | indexes on `(project_id, created_at)`, `(file_id, created_at)` |
| `diagnostics` | `id`, `analysis_id` (CASCADE), severity, category, message, rule, range, suggestion | CHECK constraints on enums |

- Enums are `VARCHAR` + `CHECK` (not native PG enums), so adding values is a plain migration.
  Constraint names follow a fixed naming convention, so autogenerated migrations are stable.
- The engine is created lazily (`pool_pre_ping`, `pool_recycle`, connect timeout). The API starts
  without a database. Driver connection errors map to 503 `database_unavailable` and are logged by
  type only, so host names and credentials never reach clients or logs.
- Performance: file listings defer `content` and `structure`, history is pruned per file, project
  structure is cached per content hash, and rescans touch only changed files.
- Editor (live) analysis is not stored. Analyses are recorded when file content is saved through the
  API or on explicit request.
- Migrations: `npm run db:migrate` (`alembic upgrade head`). The URL comes from
  `CODEWALK_DATABASE_URL`, never from `alembic.ini`. The PostgreSQL test suite (`backend/tests/db`)
  builds its schema with these same migrations, and checks that the models and migrations do not drift.

### Security foundations

- Typed settings validation: wildcard CORS is rejected, and production requires a strong secret key.
- Secrets are `SecretStr`, so they never appear in reprs, logs, or responses.
- Request bodies are limited, whether declared by `Content-Length` or streamed.
- `utils/paths.resolve_within` rejects traversal, absolute and drive paths, NUL bytes, and symlink
  escapes. Project linking and scanning use it, and scanning is confined to `CODEWALK_WORKSPACE_ROOT`.
- All SQL goes through SQLAlchemy bound parameters. Stored file paths are validated as relative POSIX
  paths.
- `integrations/http_client.ExternalHTTPClient` maps timeouts, connection errors, HTTP errors, and
  malformed bodies to typed exceptions, so an external outage cannot crash a request.
- User code is never executed.
