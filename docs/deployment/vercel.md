# Vercel deployment (prepared, not yet deployed)

CodeWalk Agent can be deployed as **one Vercel project with two services** on one domain. This page
describes what the repository implements for that. **Nothing has been deployed**: no Vercel project
exists, and the items marked *needs Vercel* have not been observed on a real deployment.

Docker Compose (`docker-compose.yml` for development, `docker-compose.prod.yml` with nginx for
self-hosting) is unchanged and remains fully supported.

Status labels used below:

- **Implemented**: in the code or configuration of this repository.
- **Validated locally**: covered by tests that ran on a developer machine (Windows).
- **Docker/CI**: needs Linux or Docker (the Linux test image, `npm run test:all:docker`, or CI).
- **Needs Vercel**: can only be confirmed on a real preview or production deployment.

## Topology

```
browser ──https──> <your-domain>  (one Vercel project, vercel.json)
                     ├─ /api/(.*) ─> service "backend"  : backend/Dockerfile.vercel (FastAPI + Node worker)
                     └─ /(.*)     ─> service "frontend" : frontend/ (Next.js)
backend ──TLS──> external managed PostgreSQL 17 with pgvector (pooled connection string)
```

- Frontend and API share one origin, so the `SameSite=Lax`, `HttpOnly`, `Secure` session cookie and
  the CSP's `connect-src 'self'` work unchanged (implemented).
- The backend runs as a **container image** (Vercel Container Images and Services are both beta).
  The image is the production image (`backend/Dockerfile`) with Vercel's port and proxy settings;
  `tests/deployment/test_vercel_config.py` fails if the two drift apart (implemented, validated
  locally). A container keeps Node (TypeScript worker), ruff and tree-sitter working.
- PostgreSQL is **not** run on Vercel. Use an external managed PostgreSQL with the `vector`
  extension (for example Neon or Supabase), in the same region as the functions.
- If the Services or container betas cause problems, the fallback is the same backend image on a
  container host (Render, Fly, Railway) with the frontend on Vercel rewriting `/api/v1/*` to it; that
  setup is not configured in this repository.

## /api routing

| Request | Service | Path the service sees |
| --- | --- | --- |
| `/api/v1/...` (auth, projects, files, uploads, analysis, AI, RAG, agent, health) | backend | `/api/v1/...` (unchanged) |
| everything else (`/`, `/app/...`, `/login`, `/healthz`, `/_next/...`, `/monaco/...`) | frontend | unchanged |

- Vercel passes the **original path** to the service (vercel.com/docs/services/routing), and FastAPI
  serves every API route under `/api/v1`. No prefix is added or stripped, so there is no doubled
  `/api` (implemented; `test_rewrites_send_only_api_paths_to_the_backend` and
  `test_every_api_route_is_under_the_api_prefix_that_vercel_routes_to_the_backend`, validated locally).
- The backend's `/` and `/metrics` are outside `/api`, so on Vercel those paths reach the frontend:
  metrics are not public.
- The browser calls the API at `NEXT_PUBLIC_API_BASE_URL`. On a Vercel build (`VERCEL=1`) with the
  variable unset, `next.config.ts` uses `/api/v1`; locally and in Docker nothing changes
  (implemented). Set it explicitly anyway (see below).
- Whether Vercel's routing behaves exactly as documented is **needs Vercel**: check
  `GET /api/v1/health/ready` on the first preview deployment.

## Environment variables (Vercel project settings)

Enter secrets as encrypted environment variables in the Vercel dashboard. Never commit them. Values
below are placeholders.

### Backend service

| Variable | Required | Secret | Value / notes |
| --- | --- | --- | --- |
| `PORT` | **yes** | no | `8000`. Vercel sends traffic to `PORT` (default 80); the image runs as a non-root user, so use an unprivileged port |
| `CODEWALK_SECRET_KEY` | **yes** | **yes** | ≥ 32 random characters, new for production. The backend refuses to start without it |
| `CODEWALK_DATABASE_URL` | **yes** | **yes** | `postgresql+psycopg://<user>:<password>@<pooled-host>/<db>?sslmode=require`. Never the development database |
| `CODEWALK_CORS_ORIGINS` | for a custom domain | no | `https://<your-domain>`. Must be `https://`. The image defaults it to empty (the deployment's own `VERCEL_*` URLs only); the development default (localhost) would be refused in production |
| `CODEWALK_DATABASE_POOL_SIZE` | recommended | no | `2`–`3`: every instance has its own pool |
| `CODEWALK_LOG_FORMAT` | no | no | `json` |
| `CODEWALK_AI_ENABLED` / `CODEWALK_AI_PROVIDER` / `CODEWALK_AI_MODEL` | for AI | no | for example `true` / `openai` / `gpt-5` |
| `CODEWALK_AI_API_KEY` | for AI | **yes** | provider key, backend only |
| `RAG_ENABLED` / `RAG_EMBEDDING_PROVIDER` / `RAG_EMBEDDING_MODEL` | for RAG | no | for example `true` / `voyage` / `voyage-code-4` |
| `VOYAGE_API_KEY` | for RAG | **yes** | embedding key, backend only |
| `CODEWALK_SHUTDOWN_TIMEOUT_SECONDS` | no | no | default `20`; keep below Vercel's 30 s SIGTERM grace period |

Set by the image (`backend/Dockerfile.vercel`): `CODEWALK_ENV=production`, `CODEWALK_HOST=0.0.0.0`,
`CODEWALK_PORT=8000`, `CODEWALK_NODE_BINARY`, `CODEWALK_CORS_ORIGINS=` (empty), `FORWARDED_ALLOW_IPS=*` (the container is reachable
only through Vercel, which sets `X-Forwarded-For`/`-Proto`, so rate limits see client addresses).

Set by Vercel and read by the backend only when `VERCEL=1`: `VERCEL_URL`, `VERCEL_BRANCH_URL`,
`VERCEL_PROJECT_PRODUCTION_URL`. Their `https://` origins are added to the allowed origins, so preview
and production deployments accept requests from their own pages without listing each generated URL
(implemented, validated locally). Whether Vercel passes these to a container at run time is
**needs Vercel**; `CODEWALK_CORS_ORIGINS` is the fallback. Production rules still apply on Vercel:
`https://` origins only, `Secure` cookies, a strong secret key.

Leave `CODEWALK_WORKSPACE_ROOT` unset: there is no persistent server filesystem (uploads cover the
same need; file contents live in PostgreSQL).

### Frontend service

| Variable | Required | Value |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | recommended | `/api/v1` (the default on Vercel builds when unset) |
| `NEXT_PUBLIC_API_TIMEOUT_MS`, `NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS` | no | defaults are fine |

`NEXT_PUBLIC_*` values are public. Never put keys, the database URL or the secret key in them.

## Request and upload limits

| Limit | Value | Where |
| --- | --- | --- |
| Vercel request body | 4.5 MB | platform; larger bodies get Vercel's own `413 FUNCTION_PAYLOAD_TOO_LARGE` |
| API request body | 6 MiB by default, **capped at 4,500,000 bytes on Vercel**; JSON `413 payload_too_large` | `CODEWALK_MAX_REQUEST_BODY_BYTES`, `Settings.request_body_limit`, `BodySizeLimitMiddleware` |
| Folder upload batch | ≤ 4 MiB of JSON as sent, ≤ 100 files | `frontend/features/workspace/folder-upload.ts` |
| Largest single upload request | 4,500,000 bytes; a file that cannot fit alone is skipped and reported | same file |
| Source file | 2 MiB | `CODEWALK_MAX_SOURCE_BYTES` (must stay below the request limit; enforced at startup) |

- The API enforces its limit itself, not only the browser: declared `Content-Length` values are
  refused before the body is read, and chunked bodies are counted as they arrive, so an oversized
  request never buffers more than the limit plus one chunk (implemented, validated locally:
  `tests/test_errors.py`, `tests/test_hosting_runtime.py`).
- Upload batches are measured as the encoded JSON, because JSON escaping can double source text
  (quotes, backslashes, newlines). A 2 MiB file still fits in one request (implemented, validated
  locally: `folder-upload.test.tsx`).
- The PostgreSQL upload tests (`tests/db/test_folder_upload_api.py`: near-limit batch stored,
  over-limit batch refused with nothing stored, malformed uploads, project isolation) are **Docker/CI**.

## TypeScript worker

The TypeScript/JavaScript analyzer is one long-lived Node process per backend instance. It has no
batches: each request is one file. Its work is bounded by:

- the source limit (2 MiB), checked before the worker is called;
- the per-file timeout (`CODEWALK_ANALYSIS_TIMEOUT_SECONDS`, 10 s); a hung worker is restarted;
- the Node heap cap (`--max-old-space-size=512`) within Vercel's default 2 GB instance;
- one request at a time per instance (requests are serialized);
- API responses carry at most 500 diagnostics; `metadata.total_diagnostics` reports the full count.

These are covered by `tests/test_hosting_runtime.py` (validated locally on Windows with Node).

The worker starts in a background thread when an instance starts, so the first TypeScript analysis
after a cold start can be slower. Containers scale to zero after 5 minutes without traffic in
production and 30 seconds in previews (needs Vercel to observe).

## Graceful shutdown

On scale-in Vercel sends `SIGTERM` and kills the container 30 s later. The backend:

1. stops accepting connections and gives in-flight requests up to
   `CODEWALK_SHUTDOWN_TIMEOUT_SECONDS` (20 s) to finish;
2. closes the TypeScript worker (end of input, then `SIGTERM`, then `SIGKILL`, about 5 s at most),
   without waiting for a request in progress, which fails instead; no new worker is started;
3. closes the database pool and exits.

If the backend is killed outright, the worker's stdin closes and it exits by itself. Tests: worker
behavior in `tests/test_hosting_runtime.py` (validated locally); the real server process receiving
`SIGTERM` and leaving no worker behind, `test_sigterm_stops_the_server_and_its_typescript_worker`,
needs Linux `/proc` (**Docker/CI**); behavior under Vercel's scale-in is **needs Vercel**.

Long requests: an agent run may take up to 240 s. On Vercel's Hobby plan the function limit is
300 s; a scale-in during such a run cancels it after the 20 s drain.

## Database and migrations

- PostgreSQL 17 with the `vector` extension (pgvector). The migration chain runs
  `CREATE EXTENSION IF NOT EXISTS vector`, so the migration role needs permission to create it, or
  enable it in the provider's console first.
- Current head revision: `c5d2e8f1a9b3`.
- Migrations never run when an instance starts. Run them as a separate step from a trusted machine
  or CI, against the **new production database only**:

  ```
  # in backend/, with CODEWALK_DATABASE_URL set for the production database in that shell only
  uv run alembic upgrade head
  uv run alembic current    # expect c5d2e8f1a9b3 (head)
  ```

  Use the provider's direct (non-pooled) connection string for migrations if its pooler does not
  support them. Take a backup before every later migration (database-backup-restore.md).

## Health and readiness

| Endpoint | Meaning |
| --- | --- |
| `GET /api/v1/health/live` | process is up (no dependencies) |
| `GET /api/v1/health/ready` | ready to serve: includes the database check |
| `GET /api/v1/health` | full health report |
| `GET /healthz` | frontend service |

Vercel does not run Docker `HEALTHCHECK`s; use these for smoke tests and uptime monitoring.

## In-memory state on serverless instances

Login and registration rate limits, AI and agent limits, and the search index cache are kept per
instance. Each new instance starts with empty counters, so the brute-force limits are weaker on
Vercel. Before launch, add a Vercel Firewall rate-limit rule for `/api/v1/auth/*` and set spending
limits with the AI provider. Persistent data (users, sessions, projects, files, analyses, embeddings)
is in PostgreSQL.

## Still requires external infrastructure or a real deployment

- A Vercel project (Services and Container Images are beta), the environment variables above, and
  `PORT=8000`.
- A managed PostgreSQL 17 database with pgvector, migrated to head as described above.
- AI and embedding provider accounts with credit.
- A custom domain (then `CODEWALK_CORS_ORIGINS=https://<domain>`) and a firewall rate-limit rule.
- Confirming on a preview deployment: routing of `/api/v1/*`, `VERCEL_*` variables inside the
  container, the 4.5 MB limit, cold starts, and `SIGTERM` handling.
