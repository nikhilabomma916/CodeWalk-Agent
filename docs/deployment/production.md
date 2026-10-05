# Production deployment (Module 22)

How to take CodeWalk Agent to a public deployment: environments, configuration, database,
migrations, checks, and what each part has been validated with. **Nothing here has been deployed**;
steps marked *manual* need the real accounts (Vercel, a managed PostgreSQL provider, AI providers,
a GitHub OAuth app).

Two supported topologies (both use the same backend image and database):

| | Vercel (recommended for this project) | Self-hosted Docker Compose |
| --- | --- | --- |
| Frontend | Vercel, service `frontend` | `frontend` container behind nginx |
| Backend | Vercel container service `backend` (`backend/Dockerfile.vercel`), routed at `/api` | `backend` container behind nginx |
| Database | managed PostgreSQL 17 + pgvector | `db` container (pgvector image) |
| Guide | [vercel.md](vercel.md) | [production-deployment.md](production-deployment.md) |

## Environments

| | Development | Preview | Production |
| --- | --- | --- | --- |
| Where | local (`npm run dev`, `docker-compose.yml`) | Vercel preview deployments (every branch/PR) | Vercel production (your domain) |
| `CODEWALK_ENV` | `development` | `production` (set by the image) | `production` (set by the image) |
| Database | local container (`codewalk`) | **a separate database** (for example a Neon branch or a second Supabase project), never production's | managed production database |
| Secrets | local `.env` (git-ignored) | Vercel env vars scoped to *Preview* | Vercel env vars scoped to *Production* |
| AI / embeddings | optional; your own keys | separate, low-limit keys | production keys with provider spend limits |
| GitHub OAuth app | one with callback `http://localhost:8000/api/v1/github/callback` | usually off (callback URLs change per preview) | its own OAuth app, callback `https://<domain>/api/v1/github/callback` |
| Allowed origins | localhost | automatic (`VERCEL_URL`, `VERCEL_BRANCH_URL`) | automatic plus `CODEWALK_CORS_ORIGINS=https://<domain>` |

Vercel scopes each environment variable to Production, Preview and/or Development: give preview
deployments their own database URL and keys, never the production ones.

## Configuration

Every backend setting is listed in [`.env.example`](../../.env.example) (a test fails if a setting
is undocumented); the Vercel-specific ones are in [vercel.md](vercel.md). Required in production:

| Variable | Notes |
| --- | --- |
| `CODEWALK_SECRET_KEY` | ≥ 32 random characters; generate per environment |
| `CODEWALK_DATABASE_URL` | `postgresql+psycopg://user:password@host/db?sslmode=require`; prefer the provider's pooled endpoint |
| `CODEWALK_DATABASE_PREPARED_STATEMENTS` | `false` when the pooler runs in transaction mode (Supabase pooler on port 6543, PgBouncer without prepared-statement support) |
| `CODEWALK_DATABASE_POOL_SIZE` | 2-3 per instance on serverless (each instance has its own pool) |
| `PORT` (Vercel) | `8000` |
| AI (optional) | `CODEWALK_AI_ENABLED`, `CODEWALK_AI_PROVIDER` (`openai`, `anthropic`, `gemini`, `openrouter`; Ollama only self-hosted behind https), model, the provider's key ([providers.md](../ai/providers.md)) |
| RAG (optional) | `RAG_ENABLED`, `RAG_EMBEDDING_PROVIDER=voyage`, `RAG_EMBEDDING_MODEL`, `VOYAGE_API_KEY` |
| GitHub (optional) | `CODEWALK_GITHUB_CLIENT_ID`, `CODEWALK_GITHUB_CLIENT_SECRET`, `CODEWALK_GITHUB_CALLBACK_URL`, `CODEWALK_TOKEN_ENCRYPTION_KEY` ([github.md](../integrations/github.md)) |

Generate random values locally, never in a shared terminal log:

```
python -c "import secrets;print(secrets.token_urlsafe(48))"                       # CODEWALK_SECRET_KEY
python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # CODEWALK_TOKEN_ENCRYPTION_KEY
```

## Preflight

`python -m app.preflight` (in `backend/`, or `docker run --rm --env-file <file> codewalk-backend:local
python -m app.preflight`) loads the settings under production rules and checks: environment, database
URL presence, secure cookies, https origins, the AI and embedding providers (configured or off),
GitHub (fully configured or off: a partial configuration fails), database connectivity, the pgvector
extension, and that the schema is at the code's Alembic head. It prints names and PASS / WARN / FAIL
only (no values) and exits 1 on any failure; `--no-db` skips the database, `--db-only` checks only it,
`--json` prints JSON.

## Database

- **PostgreSQL 17 with pgvector** (0.8.x). The migrations run `CREATE EXTENSION IF NOT EXISTS vector`;
  on providers where the migration role may not create extensions, enable `vector` in the console
  first. Use the same region as the backend.
- **Storage**: project files, versions, analyses and embeddings live in PostgreSQL; nothing is
  stored on the backend's filesystem (it is temporary on Vercel). This is appropriate at the current
  scale: a file is at most 2 MiB, a project at most 10,000 files, and only text is stored. Plan the
  database size from the number of projects; object storage would only be worth adding for binary
  assets, which CodeWalk does not store.
- **Pooling**: each backend instance keeps up to 2 × `CODEWALK_DATABASE_POOL_SIZE` connections.
  Serverless instances multiply that: use the provider's pooler and a small pool size.

### Migrations (with backup and rollback)

Migrations never run when an instance starts. Run them as a separate step before deploying code that
needs them:

```
docker build -t codewalk-backend:local backend            # the version you are about to deploy
CODEWALK_MIGRATION_DATABASE_URL='postgresql+psycopg://...' node scripts/migrate-database.mjs
```

The script refuses the local development database and local databases in general; then it runs the
preflight (database reachable, pgvector available), takes a `pg_dump` custom-format **backup**
(verified with `pg_restore --list`, with a `.sha256`, into `backups/`, which is git-ignored),
migrates to head, runs `alembic check` (no drift) and the preflight again. The URL is passed only
through the environment and is redacted from all output. Use the provider's direct (non-pooled)
connection string for migrations if its pooler does not support them.

**Rollback**: every migration in this repository is additive (new tables/columns/indexes) and the
previous application version keeps working on the newer schema; to undo the data change, restore
the backup (`pg_restore --clean --if-exists --no-owner -d <url> <dump>`) or use the provider's
point-in-time restore, then deploy the previous version. `alembic downgrade` exists for each
revision but drops the new tables' data (documented in each migration).

Validated: the script ran against a disposable local `*_test` database one revision behind head
(backup 100 archive entries, upgrade, no drift, preflight PASS) and refused the development database,
local databases, and malformed URLs.

## Deploy steps (manual)

1. Create the managed database (pgvector enabled), a separate one for previews.
2. `node scripts/migrate-database.mjs` against each (above).
3. Create the Vercel project from this repository (`vercel.json` defines the two services); add the
   variables per environment; `PORT=8000`.
4. Push a branch → preview deployment. Run the smoke test against it:
   `CODEWALK_SMOKE_TARGET=vercel CODEWALK_SMOKE_URL=https://<preview>.vercel.app npm run test:smoke`
5. Check `GET /api/v1/health/ready` (database `pass`), sign in, create a project, upload a folder,
   run diagnostics, an AI explanation, semantic search and one agent run; import a repository if
   GitHub is configured.
6. Add the custom domain, set `CODEWALK_CORS_ORIGINS=https://<domain>` and the GitHub callback URL,
   add a Vercel Firewall rate-limit rule for `/api/v1/auth/*`, set AI provider spend limits.
7. Promote to production; repeat the smoke test with the production URL.

## Health

| Endpoint | Use |
| --- | --- |
| `GET /api/v1/health/live` | process is up |
| `GET /api/v1/health/ready` | ready: includes the database check (required in production) |
| `GET /api/v1/health` | full report |
| `GET /healthz` | frontend |

## What has been validated, and how

| Item | How |
| --- | --- |
| Backend, frontend, database, migrations | `npm run test:all:docker` (PostgreSQL + pgvector, Linux) |
| Production stack (nginx, TLS off, persistence across restart) | `npm run test:deploy` |
| Vercel image (port, origins, 4.5 MB limit, SIGTERM) | run locally as Vercel would ([vercel.md](vercel.md)) |
| Preflight, migration script, pooler setting | `tests/test_production_deployment.py`, `tests/db/test_production_preflight.py`, the run above |
| **Not validated**: a real Vercel deployment, a managed database provider, live AI/GitHub accounts | manual, steps 3-7 |
