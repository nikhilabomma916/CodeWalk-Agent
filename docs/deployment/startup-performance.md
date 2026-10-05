# Container build and start-up measurements (Module 15)

Measured on 2026-10-03; nothing estimated. Reproduce with `npm run test:deploy` (start-up, restart)
and `docker build --no-cache` (builds).

**Environment**: Windows 11 (8 logical CPUs, 7.6 GiB available to Docker), Docker Desktop with
Engine 29.8.0 / Compose 5.5.1 (WSL2 backend), images built locally, base images already pulled.

## Image builds (`docker build --no-cache`, base images cached)

| Image | Cold build | Size | Notes |
| --- | --- | --- | --- |
| `codewalk-backend` | 46 s | 615 MB | Python deps (uv, locked) + TypeScript analyzer deps + Node binary |
| `codewalk-frontend` | 156 s | 428 MB | `npm ci` (all deps for the build) + `next build`; runtime holds only the standalone server |
| `codewalk-proxy` | 1 s | 81.5 MB | configuration on top of nginx-unprivileged |

With Docker's layer cache and unchanged dependencies, rebuilding after a code change took 2–34 s for
all three images together in the lifecycle runs.

## Start-up (`docker compose up -d --wait`, production compose, empty volume)

Two runs of `scripts/deploy-lifecycle.mjs --no-build` (a third, final run after a cached rebuild measured: database 2.5 s, migration 2.5 s, backend 4.5 s,
frontend 1.5 s, proxy 1.3 s, whole stack 13.6 s, restart 10.6 s). Values are "container start → first
passing health check" (job: start → exit). Health checks probe every 1 s during start-up (`start_interval`).

| Phase | Run 1 | Run 2 |
| --- | --- | --- |
| Database ready (`pg_isready`; includes first-time initialisation of the volume) | 1.2 s | 2.4 s |
| Migration job (`alembic upgrade head`, empty database → head, 5 revisions) | 1.8 s | 1.9 s |
| Backend ready (`/api/v1/health/ready`, database check required) | 4.8 s | 4.5 s |
| Frontend ready (`/healthz`) | 1.3 s | 1.4 s |
| Proxy ready (`/nginx-health`) | 1.2 s | 1.3 s |
| **Whole stack ready** (`up --wait` wall time) | **11.3 s** | **12.3 s** |
| Whole stack ready after `stop` + `up` (same volume, no migrations to apply) | 10.6 s | 10.5 s |

Before `start_interval` was added (health checks only every 5–10 s), the same stack reported ready in
18.9 s; the services themselves were not slower, the first probe simply came later.

The stack starts in dependency order (database → migration → backend → proxy, frontend in parallel),
so the wall time is roughly the sum of the database, migration, backend and proxy phases plus Docker's
own container start overhead.

## Memory at rest (`docker stats`, production-like stack, after the smoke test)

| Container | Memory |
| --- | --- |
| backend (uvicorn + TypeScript worker) | 237.5 MiB |
| frontend (Next.js standalone) | 61.2 MiB |
| db (PostgreSQL, small database) | 33.6 MiB |
| proxy (nginx) | 8.3 MiB |

## Smoke test duration

The deployment smoke test (7 tests, ~29 requests through the proxy, including two 7–9 MiB uploads)
took 1.6–3.9 s.

## Not measured

- Start-up on a Linux server (the CI Docker job runs the same lifecycle on GitHub's Ubuntu runners; its
  timings appear in the job log).
- Pulling images from a registry (no registry configured).
- Application request latency: see `docs/testing/performance-report.md` (Module 14); the proxy adds one
  local hop.
