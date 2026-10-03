# Operator runbook

Short form of the deployment and rollback procedures. Background: [production-deployment.md](production-deployment.md),
[rollback.md](rollback.md). Commands assume `/opt/codewalk` and:

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.production"
```

## Deploy a release

| # | Step | Command | Continue only if |
| --- | --- | --- | --- |
| 1 | Pull the release | `git fetch --tags && git checkout <tag>`; note the current tag/commit for rollback | checkout clean |
| 2 | Validate the environment | `$C config -q` | exit 0 (no missing required variable) |
| 3 | Check database connectivity | `$C exec db pg_isready -U codewalk` | "accepting connections" |
| 4 | Back up the database | `npm run db:backup -- --project codewalk-prod --service db` | "verified", file copied off-host |
| 5 | Build (or pull) images | `$C build` (or `$C pull` with a registry tag) | exit 0 |
| 6 | **Run migrations first** | `$C run --rm migrate` | exit 0 |
| 7 | Start the new release | `$C up -d --wait --wait-timeout 300` | exit 0, all services healthy |
| 8 | Wait for health | `$C ps` and `curl -fsS https://<host>/api/v1/health/ready` | `migrate` Exited (0), others healthy, `"status":"ok"` |
| 9 | Smoke test | `CODEWALK_SMOKE_URL=https://<host> npm run test:smoke` | all passed |
| 10 | Inspect logs | `$C logs --since 15m backend proxy \| grep -iE "error\|critical"` | nothing unexpected |
| 11 | Confirm the application | sign in, open a project, open a file, check diagnostics | works |

**Why step 6 is separate.** Measured on 2026-10-03: with a failing migration, a plain `up -d` first
replaces the running backend and proxy, then stops when the migration fails, leaving the API down
(compose exits 1). Running the migration job on its own first leaves the old release serving if it
fails (verified: same backend container, API still 200). Step 7 then re-runs the job as a no-op.

**If step 6 fails**: stop. The old release is still serving. Read `$C logs migrate`, fix forward, or
abandon the release (`git checkout <previous>`). A migration that failed inside its transaction leaves
the schema unchanged (PostgreSQL DDL is transactional); check with
`$C exec db psql -U codewalk -d codewalk -c "select version_num from alembic_version"`.

**If step 7 fails** (a service never becomes healthy): `$C ps`, `$C logs <service>`; then roll back.

## Roll back

| # | Step | Command / action |
| --- | --- | --- |
| 1 | Stop the rollout | do not retry `up`; note what failed (`$C ps`, `$C logs`) |
| 2 | Restore the previous application version | `git checkout <previous tag>`; `$C build` (or set `CODEWALK_IMAGE_TAG=<previous>` and `$C pull`) |
| 3 | **Do not downgrade migrations automatically** | the previous code may run on the newer schema if the migration was additive; see rollback.md |
| 4 | Assess schema compatibility | compare `alembic_version` with the previous release's head (`backend/migrations/versions/`) and read the new migration |
| 5 | Restore the database only if explicitly required | data loss since the backup: `npm run db:restore` into a **new** database, then switch `POSTGRES_DB` (database-backup-restore.md) |
| 6 | Start and smoke test | `$C up -d --wait --wait-timeout 300`; `npm run test:smoke` |
| 7 | Document the result | what failed, what was rolled back, data impact, follow-ups |

A database rollback (downgrade or restore) is a separate, deliberate decision: a downgrade can drop
columns or tables with their data, and a restore loses everything written after the backup.
