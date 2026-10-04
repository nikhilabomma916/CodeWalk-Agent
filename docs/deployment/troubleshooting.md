# Troubleshooting

`C="docker compose -f docker-compose.prod.yml --env-file .env.production"` (or the development file).

| Symptom | Likely cause | Check / fix |
| --- | --- | --- |
| `config`/`up` stops with "Set POSTGRES_PASSWORD…" or "Set CODEWALK_SECRET_KEY…" | required value missing | fill `.env.production`; pass `--env-file .env.production` |
| `migrate` Exited (1), backend stays "Created" | migration or database error | `$C logs migrate`; see runbook "If step 6 fails". Use `run --rm migrate` before `up` |
| `migrate` logs "CODEWALK_SECRET_KEY must be set…" | production settings validation | the migration job validates the same settings as the backend: fix the env file |
| `migrate` logs "Can't locate revision" | database is newer than this release | you are rolling back across a migration: see rollback.md |
| backend unhealthy, `/api/v1/health/ready` 503, database `fail` | database down or wrong password | `$C ps db`; `$C logs db`; for an existing volume the password changes only via `ALTER ROLE` (secrets.md) |
| backend logs "password authentication failed" after changing `POSTGRES_PASSWORD` | the env var only initialises a **new** volume | change it in the database with `ALTER ROLE`, or restore the old value |
| browser: every change fails with 403 `origin_not_allowed` | public origin differs from what the backend sees | set `CODEWALK_PUBLIC_ORIGIN` to the exact browser origin (scheme, host, port); behind a TLS-terminating LB this is required |
| sign-in "works" but you are immediately signed out (production over plain HTTP) | the browser drops the `Secure` session cookie | use HTTPS, or `http://localhost` for local runs (not `127.0.0.1` or a LAN IP) |
| API answers JSON 503 `backend_unavailable` | proxy cannot reach the backend | `$C ps backend`; `$C logs backend` |
| JSON 413 `payload_too_large` | request above 6 MiB (backend) or 8 MiB (proxy) | expected; source files are limited to 2 MiB |
| agent/AI requests end after 120 s / 300 s | proxy read timeouts | they exceed the backend's own limits; check provider latency in the backend logs |
| editor shows "Monaco assets could not be loaded" | `/monaco/vs` not served | the frontend image copies Monaco at build time; rebuild it; check `curl -I https://<host>/monaco/vs/loader.js` |
| browser console reports a Content-Security-Policy violation | a new script/style/worker source | see reverse-proxy.md (CSP); allow only what the application genuinely needs, never `'unsafe-inline'` for scripts |
| proxy exits "CODEWALK_PROXY_TLS=on but … missing or not readable" | certificate files missing or unreadable by uid 101 | place `fullchain.pem`/`privkey.pem` in `CODEWALK_TLS_DIR`; fix permissions |
| proxy unhealthy after a backend was recreated | old upstream address | nginx re-resolves every 10 s; if it persists `$C restart proxy` |
| TypeScript diagnostics missing | Node worker failed to start | `$C logs backend \| grep -i typescript` |
| AI / semantic search "unavailable" | no provider key, or the feature is disabled | expected without keys; set `CODEWALK_AI_ENABLED=true` + key, `RAG_ENABLED=true` + key |
| development: port 3000 or 8000 already in use | host dev servers and the `app` profile both running | stop one of them |
| development: frontend misses a new dependency | stale `codewalk_frontend-node-modules` volume | local-docker.md: rebuild and remove that volume (never `postgres-data`) |
| Windows: backend tests cannot load psycopg | Application Control blocks the driver | run them in Linux containers: `npm run test:all:docker` |

Useful commands:

```bash
$C ps                                   # status and health of every service
$C logs -f --tail 100 backend proxy     # follow logs (request ids match: rid=… in proxy, X-Request-ID in backend)
$C exec db psql -U codewalk -d codewalk -c "select version_num from alembic_version"
docker inspect --format '{{json .State.Health}}' codewalk-prod-backend-1   # health check history
```
