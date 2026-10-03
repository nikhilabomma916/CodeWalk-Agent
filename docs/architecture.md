# Architecture

This document describes the architecture of Batch 1 (Modules 1–3: foundation, editor, API), Batch 2
(Modules 4–6: code analysis, project intelligence, persistence), Batch 3 (authentication,
application areas, project ownership, history), Batch 4 (Modules 7–9: AI analysis, AI
explanations and fix suggestions, project-aware search), and Module 10 (semantic retrieval), and where
later modules plug in.

> **Design history.** The original planning documents ([PRD](PRD.md),
> [system architecture](system-architecture.md), [workflows](workflows.md),
> [project intelligence](project-intelligence.md)) described this flow:
> User → Frontend → Backend API → Code Execution → Code Analysis → Error Detection → AI Agent →
> Code Explanation → Frontend. The implementation keeps that shape **except for code execution**:
> user code is analyzed statically and is never run. The sections below describe what is built.

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

### Routes and authentication

| Route | Access | Content |
| --- | --- | --- |
| `/` | public | redirects to `/app/projects` or `/login` |
| `/login`, `/register` | signed-out | forms; signed-in users are sent on to `?next=` (only `/app…` paths are accepted) |
| `/app` | signed-in | redirects to `/app/projects` |
| `/app/coding` | signed-in | the editor workspace. `?project=<id>&file=<path>&line=<n>` opens a server project/file |
| `/app/projects` | signed-in | project list and creation |
| `/app/projects/[projectId]` | signed-in | project details, explorer, analyze/edit/delete |
| `/app/history` | signed-in | activity, filterable with `?project=<id>&type=<event_type>` |

`features/auth/auth-context.tsx` (`AuthProvider` in the root layout) is the only place that knows
about the session. It exposes `status` (`loading | authenticated | unauthenticated | error`), `user`,
`login`, `register`, `logout`, and `refresh`. On load it asks `GET /auth/me`. The API client reports
every 401 `not_authenticated` response (`onSessionEnded`), and the provider then signs the UI out,
wherever the request came from.

`RequireAuth` wraps `/app/*`. Signed-out users go to `/login?next=<current path>`, and a deliberate
sign-out goes to plain `/login`. If the session cannot be checked (backend down), it shows the error
and a retry instead of redirecting, so an outage never looks like a sign-out and cannot cause a
redirect loop. `RedirectIfAuthenticated` wraps `/login` and `/register`. These guards are UX only:
the backend authorizes every request itself.

The `/app` layout mounts `WorkspaceProviders` (confirm dialog, workspace state, cursor) once, above
`AppShell` (navigation rail + account menu). The open project, tabs, and unsaved buffers therefore
survive navigation between Coding, Projects, and History. Monaco models are recreated from the buffers
when the editor remounts. Signing out first closes the project, which asks about unsaved changes.

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
| `ServerProjectSource` | Coding → "Open a project", a Projects/History link, or New project → "Server" (PostgreSQL) | `PATCH /projects/{id}/files/{file}` |

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

### Authentication and ownership (Batch 3)

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `email` (unique, lower-case), `name`, `password_hash` (Argon2id), `is_active`, `last_login_at`, timestamps | |
| `auth_sessions` | `id`, `user_id` (CASCADE), `token_hash` (unique SHA-256), `expires_at` | expired rows are removed at the user's next sign-in |
| `projects.owner_id` | → users (CASCADE) | unique index `(owner_id, lower(name))` replaces the global name index |
| `file_versions` | `file_id` (CASCADE), `version`, `content`, `content_hash`, `source`, `author_id` (SET NULL) | unique `(file_id, version)`; pruned per file |
| `activity_events` | `user_id` (CASCADE), `event_type`, `project_id`/`file_id`/`analysis_id` (SET NULL), `project_name`, `file_path`, `details` JSONB, `created_at` | indexes `(user_id, created_at)`, `(project_id, created_at)` |

Migration `4814067a0efe` adds these. Projects from before accounts cannot be given an owner
automatically, so the upgrade refuses to run while such projects exist, unless
`-x delete_unowned_projects=true` is passed. Downgrade restores the Batch 2 schema.

- **Session:** `get_current_user` (in `api/deps.py`) reads the cookie, checks the token's shape, and
  looks up an unexpired session of an active user. Every user-data service (`ProjectService`,
  `FileService`, `AnalysisService`, `ProjectIntelligenceService`, `HistoryService`) is built with
  that user. Repositories take the owner id in every project query, so a wrong id is simply
  "not found". There is no code path that loads a project without its owner.
- **History:** `services/activity.ActivityRecorder.record()` is called by the services before they
  commit, so an event exists exactly when its action was persisted. Failed or no-op actions (a
  conflict, an unchanged save) record nothing.
- **Abuse limits:** `core/rate_limit.AttemptLimiter` counts failed sign-ins per client address and
  email, and registrations per address. It is in-process, so each worker counts separately.
- **CSRF:** `SameSite=Lax` cookie + `OriginCheckMiddleware` (state-changing requests with a foreign
  `Origin` get 403) + CORS restricted to `CODEWALK_CORS_ORIGINS` with credentials.

### AI assistance (Modules 7 and 8)

```
services/ai/
  base.py         AIProvider protocol, normalized AIError hierarchy, ProviderStatus
  providers/      registry (create_provider) + anthropic.py (official SDK)
  prompts/        system prompts and rendering (common, code_analysis, explanation, fix)
  outputs.py      the JSON shapes the model must return (schema + validation)
  edits.py        CodeEdit conversion/validation/application, safety limits, unified diffs
  service.py      AIService (app-wide) and AIAssistant (per request)
```

- **Provider independence:** application code depends only on `AIProvider.status()` (no network)
  and `generate_structured(system, user, schema, …)`, which returns a JSON object or raises an
  `AIError`. The Anthropic provider uses `messages.create` with structured outputs
  (`output_config.format`) and reasoning `effort`. On current models it adds server-side refusal
  fallback (`fallbacks: "default"`). It maps SDK exceptions to `ai_timeout`, `ai_rate_limited`,
  `ai_unavailable`, `ai_provider_error`, `ai_context_too_large`, `ai_refused`, and
  `ai_malformed_response`. A new provider is one class plus one registry entry.
- **Flow:** editor buffer + deterministic diagnostics → (ownership check and project context) →
  prompt with numbered lines → provider → schema validation (`outputs.py`) → normalization against
  the real text → response → (record + history when a project is given).
- **Prompts** require the model to analyze only the supplied evidence, separate observation from
  inference, cite line numbers, never claim execution, report security issues only with evidence,
  avoid unrelated rewrites, and treat any instructions inside code as data. Review prompts tell the
  model not to repeat the deterministic diagnostics.
- **Fixes are proposals:** the model returns whole-line edits, which `edits.py` converts to exact
  `CodeEdit` ranges, validates, and applies to the submitted text only to produce
  `suggested_code` + diff. The browser shows a Monaco diff, and **Apply** replaces the editor content
  as one undoable edit, only if the buffer still equals `original_code`. Saving remains a separate,
  explicit action.
- **Persistence:** AI results for project files are stored in `analyses`
  (`ai_review`/`ai_explanation`/`ai_fix_suggestion`, newest 20 per file and type) with provider,
  model, usage, a hash of the code, and the validated answer, but not the code itself. Each result
  also gets an `ai.*` history event. Migration `aa335eec9810` only widens the two CHECK constraints.
- **Abuse limits:** a per-user request limit (`CODEWALK_AI_MAX_REQUESTS` per window), the existing
  body limit, `max_source_bytes` for code, and bounded context.
- **Frontend:** `features/ai/ai-assist-context.tsx` holds AI status and the current
  explanation/fix/review per workspace. The UI lives in the existing workflow: *Explain* on Problems
  rows, the explanation beside the Problems list, the fix diff over the editor, and an *AI Review*
  bottom tab. There is no chat interface.

### Project search and context (Module 9)

`services/project_search/` builds an in-memory `ProjectIndex` from Module 5
(`ProjectIntelligenceService.structure_of`, using the per-file structure cache keyed by content
hash). The index holds files' lines, symbols, imports, and import relationships. It is cached per
project (LRU of 32, per process) under the fingerprint of all `(path, content_hash)` pairs, which
one metadata query reads, so unchanged projects are never re-parsed and any save invalidates the
entry. `ranking.py` holds the fixed, documented weights. `ProjectContextBuilder` (`context.py`)
selects bounded context in a fixed order: definitions of names quoted in diagnostics, query or
current-symbol matches, definitions of names the file imports, and the files that import it.
Module 10 adds a fifth step after these (below).

### Semantic retrieval (Module 10)

Module 10 adds to Module 9; it does not replace it. Deterministic search is the default and is
unchanged.

```
ProjectIndex (Module 9, from Module 5 symbols)
   │ chunk_file: one chunk per function/class/method, 40-line windows for the rest
   ▼
EmbeddingProvider ── VoyageEmbeddingProvider (voyage-code-4, input_type document/query)
   │ vectors (1024 floats)
   ▼
code_chunks (PostgreSQL + pgvector, HNSW cosine index)
   │ SemanticRetriever.search: project_id + current content hash filter, cosine distance
   ▼
ProjectSearchService (mode semantic | hybrid → RRF)    ProjectContextBuilder step 5 → AI features
```

- **`services/retrieval/`**: `base.py` (the `EmbeddingProvider` protocol, `InputType`, and the
  `RetrievalError` hierarchy), `providers/` (registry, `voyage.py` over `httpx`: batching by count
  and estimated tokens, status codes mapped to typed errors), `chunking.py`, `fusion.py` (RRF,
  k = 60), and `service.py`. `RetrievalService` (one per app) selects the provider and holds status,
  per-user limits, and a small query-embedding cache. `SemanticRetriever` (one per request, for the
  signed-in user) indexes and searches.
- **Storage**: `code_chunks` (`project_id`, `file_id` with cascading foreign keys, `content_hash`,
  `chunk_hash`, line range, symbol, `embedding_model`, `vector(1024)`). Source text is not copied;
  snippets come from `files.content`. `app/db/vector.py` is a small SQLAlchemy type for pgvector
  (no extra dependency), registered for reflection so `alembic check` sees the column.
- **Ownership and freshness**: every operation receives the project and index from
  `ProjectSearchService.project_index` (owner-checked). Queries filter on `project_id` and join
  `files` on `content_hash`, so chunks of edited files are never returned. pgvector's iterative
  HNSW scan (`hnsw.iterative_scan = relaxed_order`) keeps filtered queries complete; results are
  re-sorted exactly.
- **Incremental indexing**: a file is re-chunked only when its content hash changed. Chunks whose
  text hash is unchanged keep their stored vectors, and only the rest are embedded. Each group of
  up to 256 texts is committed on its own, and runs are bounded by `CODEWALK_RAG_MAX_CHUNKS_PER_RUN`.
  Indexing is triggered explicitly (API / *Index project*), never by a search or a save, because
  it sends code to the provider.
- **Hybrid ranking**: the top 50 deterministic and top 20 semantic results are fused by rank only;
  raw scores are never mixed. A location found by both lists is one result carrying both ranks.
- **Context**: `ProjectContextBuilder` runs the four deterministic steps first. Step 5 embeds the
  diagnostics, query, and the code around the line, and adds up to 4 similar chunks from other
  files within the remaining snippet/character budget. `metadata.semantic` records whether it was
  used and why not. `AIAssistant` passes the per-request retriever through, so the AI endpoints get
  semantic context with no prompt or endpoint changes.

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
- User code is never executed, including by the AI features. Provider credentials are server-side
  `SecretStr` settings, never returned (`/ai/status` reports only whether one is configured) and
  never logged. Provider error bodies are not passed through to clients.
- Search, snippets, and context read only the caller's own project records, never the filesystem.
  Paths are validated (no `..`, absolute, or drive paths), ignored and secret files are excluded,
  and result and snippet sizes are bounded.
- Semantic retrieval queries are always scoped to the caller's project. `VOYAGE_API_KEY` is a
  server-side `SecretStr`; `/rag/status` never calls the provider or returns the key. Indexing sends
  source code to the embedding provider and only runs when a user asks for it.

### Known limitations (Batch 4 and Module 10)

- Only the Anthropic provider is implemented. AI quality depends on the model, and answers are
  advisory.
- Only the Voyage embedding provider is implemented, and the vector width is fixed at 1024 (a
  different width needs a migration and a re-index). Semantic quality depends on the model.
- Indexing is manual and synchronous (bounded per run); files edited after indexing drop out of
  semantic results until the next run.
- Symbol extraction covers Python and JS/TS, and other languages are searched and chunked by lines.
- Fix suggestions change one file and need files under 100,000 characters.
- Rate limits and the search index cache are per process.
