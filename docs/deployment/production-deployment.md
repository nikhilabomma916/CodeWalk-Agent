# Production deployment

Target: one Linux host with Docker Engine 25+ and Compose v2, a DNS name pointing at it, and ports
80/443 open. All commands run from a checkout of the release you are deploying.

## 1. Prepare the host

```bash
git clone https://github.com/nikhilabomma916/CodeWalk-Agent.git /opt/codewalk
cd /opt/codewalk
git checkout <release tag or commit>
cp .env.production.example .env.production
chmod 600 .env.production
```

Fill in `.env.production` (variables: [environment.md](environment.md); generating and storing the
secrets: [secrets.md](secrets.md)):

- `POSTGRES_PASSWORD`, `CODEWALK_SECRET_KEY`: generated on the server, never committed.
- `CODEWALK_PUBLIC_ORIGIN=https://codewalk.example.com`
- `CODEWALK_PROXY_TLS=on`, and certificates in `deploy/certs/` (or `CODEWALK_TLS_DIR`): see
  [reverse-proxy.md](reverse-proxy.md#https).
- Optional: `CODEWALK_AI_ENABLED=true` + `ANTHROPIC_API_KEY`, `RAG_ENABLED=true` + `VOYAGE_API_KEY`.
  Without them the application runs normally and reports AI and semantic search as unavailable.

## 2. Validate before starting

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production config -q   # fails on a missing required value
```

Do not run `config` without `-q` in shared terminals or CI logs: the rendered configuration contains
the secrets.

## 3. Build (or pull) and start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production build
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait --wait-timeout 300
```

`up --wait` starts the database, runs the migration job, starts backend and frontend, then the proxy,
and returns when every service is healthy (exit code non-zero otherwise). With a registry, set
`CODEWALK_IMAGE_REGISTRY` and `CODEWALK_IMAGE_TAG` and use `pull` instead of `build`.

## 4. Verify

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps        # all healthy, migrate Exited (0)
curl -fsS https://codewalk.example.com/api/v1/health/ready                      # "status":"ok", database pass
CODEWALK_SMOKE_URL=https://codewalk.example.com npm run test:smoke             # needs uv (see README)
docker compose -f docker-compose.prod.yml --env-file .env.production logs --since 10m backend proxy
```

The smoke test registers a throwaway `smoke-…@example.com` account and project; delete it afterwards if
you do not want it in production data. Then sign in through the browser and open a project.

## 5. Updating to a new release

Follow [runbook.md](runbook.md). In short: back up the database, check out the new release, build,
run the migration job **on its own first** (`run --rm migrate`; if it fails, the old release keeps
serving), then `up -d --wait` and the smoke test. Running `up` directly with a failing migration takes
the API down: compose replaces the backend and proxy before the migration job reports failure
(measured; see the runbook).

## Operations

- **Logs**: every container logs to stdout/stderr (`docker compose logs`). The backend writes JSON lines
  (`CODEWALK_LOG_FORMAT=json`) with a request id that matches the proxy's `rid=` field. Ship them with your
  platform's log driver (for example `journald` or a collector reading Docker's JSON logs); nothing is
  written inside the containers. Configure Docker log rotation (`/etc/docker/daemon.json`:
  `"log-opts": {"max-size": "50m", "max-file": "5"}`).
- **Never logged**: passwords, session tokens, cookies, `Authorization` headers, API keys, file contents.
  The proxy logs the path without the query string.
- **Backups**: [database-backup-restore.md](database-backup-restore.md). Schedule `npm run db:backup`
  (cron/systemd timer) and copy the files off the host.
- **Resources**: measured at rest: backend 238 MiB, frontend 61 MiB, proxy 8 MiB (startup-performance.md); PostgreSQL's `shm_size` is 256 MB.
  The backend opens at most `2 × CODEWALK_DATABASE_POOL_SIZE` (default 10) database connections.
- **Scaling**: run one backend process (rate limits are per process; see architecture.md).
- **Firewall**: expose only 80/443. PostgreSQL is not published at all.
