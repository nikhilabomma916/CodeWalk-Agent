# Deployment architecture

CodeWalk Agent runs as five containers defined in `docker-compose.prod.yml`. Only the reverse
proxy is published; everything else talks over private Docker networks.

```text
                 Internet / LAN
                       │  :80 / :443 (only published ports)
               ┌───────▼────────┐
               │ proxy (nginx)  │  TLS, routing, body limits, timeouts, gzip for assets
               └───┬────────┬───┘
   /api/...        │        │   everything else (/, /_next, /monaco, /healthz)
       ┌───────────▼──┐  ┌──▼────────────┐
       │ backend      │  │ frontend      │   network "edge" (has outbound access:
       │ FastAPI :8000│  │ Next.js :3000 │   the backend calls the AI providers)
       └──────┬───────┘  └───────────────┘
              │ network "data" (internal: no outbound access, nothing published)
       ┌──────▼───────┐   ┌──────────────┐
       │ db           │◄──┤ migrate      │  one-shot: alembic upgrade head, before the backend
       │ PostgreSQL 17│   └──────────────┘
       │ + pgvector   │  volume db-data
       └──────────────┘
```

| Service | Image | Runs as | Health check | Restart |
| --- | --- | --- | --- | --- |
| `proxy` | `codewalk-proxy` (`deploy/nginx/Dockerfile`, nginx 1.28 unprivileged) | uid 101 | `GET /nginx-health` | unless-stopped |
| `frontend` | `codewalk-frontend` (`frontend/Dockerfile`, Next.js standalone on Node 22) | `node` (uid 1000) | `GET /healthz` | unless-stopped |
| `backend` | `codewalk-backend` (`backend/Dockerfile`, Python 3.12 + Node 22 binary) | `codewalk` (uid 10001) | `GET /api/v1/health/ready` | unless-stopped |
| `migrate` | same backend image, command `alembic upgrade head` | uid 10001 | none (one-shot job) | no |
| `db` | `pgvector/pgvector:pg17-bookworm` (PostgreSQL 17, pgvector 0.8.7) | postgres | `pg_isready` | unless-stopped |

## Request routing

| Path | Goes to | Notes |
| --- | --- | --- |
| `/api/...` | backend | every backend route is under `/api/v1`; read timeout 120 s (AI requests up to 90 s) |
| `/api/v1/agent/...` | backend | read timeout 300 s (an agent run may take up to 240 s) |
| `/_next/static/...`, `/monaco/...` | frontend | gzip; Next.js marks hashed assets immutable |
| `/` and every other path | frontend | pages are rendered per request (CSP nonce) |
| `/nginx-health` | proxy itself | `{"status":"ok"}` for the container health check |

The browser loads the app and calls the API **on the same origin** (the frontend image is built with
`NEXT_PUBLIC_API_BASE_URL=/api/v1`), so CORS is not involved in production and one image serves any
domain. The backend's interactive docs (`/docs`, `/api/v1/openapi.json`) are off in production.

## Startup order and readiness

1. `db` starts; healthy when `pg_isready` succeeds.
2. `migrate` runs `alembic upgrade head` once and exits. A non-zero exit stops the rollout: the backend
   depends on `service_completed_successfully` and is never started against a half-migrated schema.
3. `backend` starts; healthy when `/api/v1/health/ready` returns 200. In production the database is a
   **required** readiness check, so a database outage turns readiness into 503.
4. `frontend` starts in parallel; healthy when `/healthz` returns 200.
5. `proxy` starts after both are healthy.

`docker compose ... up -d --wait` returns only when every service is healthy (or fails).

## Health endpoints

| Endpoint | Meaning | Used by |
| --- | --- | --- |
| `GET /api/v1/health/live` | the backend process answers (no dependency checks) | operators, external monitors |
| `GET /api/v1/health/ready` | dependency checks pass (database required in production): 200, else 503 | backend container health check |
| `GET /api/v1/health` | full report (same as ready) | dashboards |
| `GET /healthz` (frontend) | the Next.js server answers | frontend container health check |
| `GET /nginx-health` (proxy) | nginx answers | proxy container health check |

Health responses contain status, version, environment, uptime and per-check status/latency. They never
contain connection strings, passwords, keys or stack traces (`backend/tests/test_database_unavailable.py`).

## Design decisions

- **nginx** as the reverse proxy: small, well understood, does TLS termination, body limits, per-route
  timeouts and static compression in plain configuration, and has an official unprivileged image.
  Upstreams use Docker's DNS with `resolve`, so a recreated container is found without reloading nginx.
- **Migrations as a separate one-shot job**, not inside the backend's start command: exactly one
  migrator per deployment, never one per replica, and a failure is visible as a failed job.
- **One backend process.** Rate limits are kept in process memory (Module 14 limitation); running several
  workers or replicas would multiply them. Scale vertically, or add a shared limiter first.
- **Read-only containers**: every application container has a read-only root filesystem, no Linux
  capabilities and `no-new-privileges`; only `/tmp` (and Next.js's cache) are writable tmpfs mounts.
- **Development and production are separate compose projects** (`codewalk` vs `codewalk-prod`) with
  separate volumes. Nothing in the production stack can touch the development database.

See also: [reverse-proxy.md](reverse-proxy.md), [environment.md](environment.md),
[startup-performance.md](startup-performance.md).
