# Environment configuration

This page covers Docker Compose. For the prepared Vercel setup (services, `PORT`, `VERCEL_*` origins) see
[vercel.md](vercel.md).

Three places hold configuration, with different rules:

| Where | Read by | May contain secrets? |
| --- | --- | --- |
| `.env.production` (from `.env.production.example`) | `docker compose -f docker-compose.prod.yml --env-file …` | yes: git-ignored, `chmod 600`, on the server only |
| `.env` (from `.env.example`) | development: backend, frontend dev server, `docker-compose.yml` | yes (local only, git-ignored) |
| Frontend build arguments `NEXT_PUBLIC_*` | inlined into the browser bundle at build time | **never** |

## Production stack variables (`docker-compose.prod.yml`)

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `POSTGRES_PASSWORD` | **yes** | – | database password; URL-safe characters (it is embedded in the backend's database URL) |
| `CODEWALK_SECRET_KEY` | **yes** | – | ≥ 32 random characters; the backend refuses to start in production without it (see secrets.md for what it protects) |
| `CODEWALK_PUBLIC_ORIGIN` | recommended | empty | public `https://` origin; becomes the backend's allowed origin list. Empty = same-origin only |
| `CODEWALK_PROXY_TLS` | no | `off` | `on`: nginx terminates TLS with certificates from `CODEWALK_TLS_DIR` |
| `CODEWALK_BIND_ADDRESS` | no | `0.0.0.0` | host interface for the proxy ports (`127.0.0.1` for local runs) |
| `CODEWALK_HTTP_PORT` / `CODEWALK_HTTPS_PORT` | no | `80` / `443` | published proxy ports |
| `CODEWALK_TLS_DIR` | no | `./deploy/certs` | host folder with `fullchain.pem` and `privkey.pem`, mounted read-only |
| `CODEWALK_ACME_DIR` | no | `./deploy/acme` | ACME HTTP-01 webroot, mounted read-only |
| `POSTGRES_USER` / `POSTGRES_DB` | no | `codewalk` | database role and name |
| `CODEWALK_DATABASE_POOL_SIZE` | no | `5` | connections per pool (up to twice this under load) |
| `CODEWALK_DATABASE_STATEMENT_TIMEOUT_SECONDS` | no | `30` | PostgreSQL cancels a single application statement after this long (the request fails with 503); migrations are not affected |
| `CODEWALK_METRICS_ENABLED` | no | `true` | backend `GET /metrics` (Prometheus text) on the internal network; not routed by the proxy. See docs/operations/observability.md |
| `CODEWALK_IMAGE_REGISTRY` / `CODEWALK_IMAGE_TAG` | no | empty / `local` | which images run; a rollback changes the tag |
| `CODEWALK_LOG_FORMAT` / `CODEWALK_LOG_LEVEL` | no | `json` / `INFO` | backend logging |
| `CODEWALK_AI_ENABLED`, `CODEWALK_AI_PROVIDER`, `CODEWALK_AI_MODEL` | no | `false`, provider defaults | AI assistance and the agent |
| `ANTHROPIC_API_KEY` or `CODEWALK_AI_API_KEY` | no | empty | AI provider key (backend only) |
| `OPENAI_API_KEY`, `CODEWALK_AI_BASE_URL` | no | empty | experimental `openai` provider key and optional compatible server (https only) |
| `RAG_ENABLED`, `RAG_EMBEDDING_PROVIDER`, `RAG_EMBEDDING_MODEL` | no | `false`, provider defaults | semantic retrieval |
| `VOYAGE_API_KEY` | no | empty | embedding provider key (backend only) |

Compose stops with an error naming the variable when a required value is missing
(`npm run test:infra` checks this). Optional keys may be absent: the application starts and reports
AI/retrieval as unavailable; deterministic analysis, search and everything else keep working.

The compose file sets these for the backend itself: `CODEWALK_ENV=production`,
`CODEWALK_DATABASE_URL` (built from the `POSTGRES_*` values, host `db`), `CODEWALK_CORS_ORIGINS`
(from `CODEWALK_PUBLIC_ORIGIN`), and `FORWARDED_ALLOW_IPS=*` (uvicorn trusts the proxy's
`X-Forwarded-For`/`-Proto`; safe because the backend port is never published).

Every other backend setting (limits, timeouts, history sizes; see `.env.example`) keeps its default.
To change one, add it to the `x-backend-environment` block in `docker-compose.prod.yml`.

## What production enforces (backend refuses to start otherwise)

- `CODEWALK_SECRET_KEY` set, ≥ 32 characters, not a known placeholder.
- Every allowed origin is `https://`; the wildcard `*` is rejected in every environment.
- Session cookies are `Secure` (`CODEWALK_SESSION_COOKIE_SECURE=false` is refused).
- Interactive API docs are off; HSTS is sent.

Startup errors name the problem but never echo the configured values.

## Frontend build arguments

| Build argument | Default in the image | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/v1` | API base: a same-origin path behind the proxy, or an absolute URL |
| `NEXT_PUBLIC_API_TIMEOUT_MS` | `10000` | browser request timeout |
| `NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS` | `15000` | status-bar health polling |

They are public by definition. Provider keys, the database URL and the secret key are backend-only and
never reach the frontend image (`npm run test:infra` scans the built bundle).

## Limits (defaults; see reverse-proxy.md for the proxy's)

| Limit | Value | Where |
| --- | --- | --- |
| Source file size (analysis, storage) | 2 MiB | backend `CODEWALK_MAX_SOURCE_BYTES` |
| Request body | 6 MiB, JSON 413 (at most 4.5 MB on Vercel) | backend `CODEWALK_MAX_REQUEST_BODY_BYTES` |
| Request body (outer cap) | 8 MiB, JSON 413 | nginx `client_max_body_size` |
| AI request | 90 s | `CODEWALK_AI_TIMEOUT_SECONDS`; proxy read timeout 120 s |
| Agent run | 240 s, 8 steps, 3 proposed changes | `CODEWALK_AGENT_*`; proxy read timeout 300 s |
| Analyzer per file | 10 s | `CODEWALK_ANALYSIS_TIMEOUT_SECONDS` |
| Database connect | 5 s | `CODEWALK_DATABASE_CONNECT_TIMEOUT_SECONDS` |
| One SQL statement | 30 s | `CODEWALK_DATABASE_STATEMENT_TIMEOUT_SECONDS` |
| Draining requests on SIGTERM | 20 s, then the TypeScript worker and pool close | `CODEWALK_SHUTDOWN_TIMEOUT_SECONDS` (below the 30 s `stop_grace_period`) |
| Rate limits | login 10/15 min, register 20/h, AI 30/10 min, agent 20/10 min, per process | `CODEWALK_*_MAX_*` |
