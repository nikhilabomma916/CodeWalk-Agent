# Architecture

This document describes the architecture established in Batch 1 (Modules 1–3) and where later
modules plug in.

## Layers

```
Frontend (Next.js)
  components/ui        presentational primitives, no business logic
  features/*           feature UI + state (workspace context/reducer, explorer, editor, problems)
  services/api         the only place that performs HTTP; validates every response with zod
        │  HTTP, JSON, /api/v1
Backend (FastAPI)
  api/routes           HTTP concerns only: parse, call a service, return a schema
  api/deps.py          dependency providers (settings, services; DB sessions/repositories later)
  services             business logic, framework-agnostic
  repositories         data access (arrives with Module 8; services will receive repositories via deps)
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

The server-side project/file APIs (Module 7) will add a backend-backed `ProjectSource`, so UI
components will not need to change. Every source applies the same ignore rules
(`lib/project-paths.ts`), skips `.env` files, refuses binary or non-UTF-8 files, and caps file size
and entry count.

### Diagnostics

`types/diagnostics.ts` defines the `Diagnostic` shape: severity, message, file, line, column,
source, code, and suggested action. The shape matches the target backend analysis response. Diagnostics
are stored per *producer* (`state.diagnostics[source][file]`). The only producer today is Monaco's
built-in syntax validation (semantic TypeScript checks are disabled because the editor has no
project type information). Module 5 adds the backend analysis engine as a second producer.
The Problems panel and status bar already aggregate all producers.

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
produce `unavailable` (HTTP 503). Optional failures produce `degraded`. No checks are registered yet,
so the database and AI provider are **absent** from the report rather than claimed healthy. Their
modules will register checks.

### Security foundations

- Typed settings validation: wildcard CORS is rejected, and production requires a strong secret key.
- Secrets are `SecretStr`, so they never appear in reprs, logs, or responses.
- Request bodies are limited, whether declared by `Content-Length` or streamed.
- `utils/paths.resolve_within` rejects traversal, absolute and drive paths, NUL bytes, and symlink
  escapes. Module 7's file APIs must use it.
- `integrations/http_client.ExternalHTTPClient` maps timeouts, connection errors, HTTP errors, and
  malformed bodies to typed exceptions, so an external outage cannot crash a request.
- User code is never executed.
