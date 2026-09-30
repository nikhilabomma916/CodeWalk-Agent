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
| 404 | `not_found` | unknown route or resource |
| 405 | `method_not_allowed` | wrong HTTP method |
| 413 | `payload_too_large` | body exceeds `CODEWALK_MAX_REQUEST_BODY_BYTES` |
| 422 | `validation_error` | body/query failed validation (`details` lists fields; input values are never echoed) |
| 500 | `internal_error` | unexpected failure (details are logged server-side only) |
| 503 | `service_unavailable` | a required dependency is unavailable |
