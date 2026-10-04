# Local Docker

Two compose files, two separate projects:

| File | Project | Purpose | Database volume |
| --- | --- | --- | --- |
| `docker-compose.yml` | `codewalk` | development (hot reload) | `codewalk_postgres-data` (your development data) |
| `docker-compose.prod.yml` | `codewalk-prod` (or `-p <name>`) | production images, locally or on a server | `<project>_db-data` |

> Never run `docker compose down -v` against the development project unless you mean to delete every
> development project: `-v` deletes `codewalk_postgres-data`. Plain `down` keeps it.

## Development stack

Prerequisites: Docker Desktop (or Docker Engine 25+ with Compose v2), and a repository `.env` with
`POSTGRES_PASSWORD` set (copy `.env.example`; generate the password as described there).

```bash
docker compose up -d postgres                 # database only; run backend/frontend on the host
docker compose --profile app up -d --build    # database + migrations + backend + frontend in containers
docker compose --profile app logs -f backend frontend
docker compose --profile app stop             # stop (data kept)
```

| Service | URL | Notes |
| --- | --- | --- |
| frontend | http://localhost:3000 | Next.js dev server; source mounted from `./frontend`, polling for changes |
| backend | http://localhost:8000/api/v1 | uvicorn `--reload`; `./backend/app` mounted read-only; docs at http://localhost:8000/docs |
| postgres | 127.0.0.1:5432 | pgvector image; `codewalk` and `codewalk_test` databases |

All ports bind to `127.0.0.1`. The `app` profile is opt-in, so `docker compose up -d postgres` and
`npm run db:up` behave exactly as before. The `migrate` step runs `alembic upgrade head` against the
development database (a no-op when it is already at head; it never downgrades or resets).

The frontend's Linux `node_modules` and `.next` cache live in named volumes
(`codewalk_frontend-node-modules`, `codewalk_frontend-next`). After changing `frontend/package.json`:
`docker compose --profile app build frontend && docker volume rm codewalk_frontend-node-modules`
(stop the frontend first). These volumes hold no application data.

Do not run the host dev servers (`npm run dev`) and the `app` profile at the same time: both use ports
3000 and 8000.

## Production stack on your machine

Useful to test images, the proxy, CSP and health checks before deploying. Plain HTTP on localhost.

```bash
cp .env.production.example .env.production      # then set the two required secrets (see secrets.md)
# For a local run also set: CODEWALK_BIND_ADDRESS=127.0.0.1, CODEWALK_HTTP_PORT=8080, CODEWALK_HTTPS_PORT=8443
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait
# browse to http://localhost:8080
CODEWALK_SMOKE_URL=http://127.0.0.1:8080 npm run test:smoke
docker compose -f docker-compose.prod.yml --env-file .env.production down   # data kept
```

Use `http://localhost` (not `127.0.0.1`) in the browser: production session cookies are `Secure`, and
browsers accept Secure cookies over plain HTTP only for `localhost`.

The fully automated version (own project and volume, throwaway secrets, restart and persistence check,
timings): `npm run test:deploy`.
