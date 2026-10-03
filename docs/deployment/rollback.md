# Rollback

Application rollback and database rollback are different operations with very different risks.

## Application rollback (routine, safe)

The images are stateless. Rolling back means running the previous images again:

```bash
git checkout <previous tag>          # or CODEWALK_IMAGE_TAG=<previous> with a registry
docker compose -f docker-compose.prod.yml --env-file .env.production build    # or: pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait --wait-timeout 300
CODEWALK_SMOKE_URL=https://<host> npm run test:smoke
```

The migration job runs again with the previous release's migrations. Alembic does **not** downgrade
on `upgrade head`: if the database is already at a newer revision that the previous release does not
know, the job fails with "Can't locate revision". The previous release cannot start against a schema it
does not know. Then either fix forward, or decide on a database rollback (below).

## Database rollback (exceptional, potentially destructive)

Nothing in this repository downgrades a database automatically, and it must not be scripted into a
deployment. Options, in order of preference:

1. **Fix forward.** Ship a corrected release with a new migration. No data loss.
2. **Keep the newer schema.** If the new migration only added tables/columns (most of CodeWalk's
   migrations are additive), the previous code may run against it, but Alembic refuses an unknown
   revision. Do this only with a reviewed, deliberate procedure (stamping is a manual decision).
3. **Downgrade** (`alembic downgrade <revision>` in a one-off backend container). Read the migration's
   `downgrade()` first: it may drop columns or tables **and their data** (for example the pgvector
   migration drops `code_chunks`, the agent migration drops `agent_runs`/`agent_actions`). Back up first.
4. **Restore a backup** taken before the deployment, into a new database, then switch to it
   ([database-backup-restore.md](database-backup-restore.md)). Everything written after the backup is lost.

Whatever is chosen: take a fresh backup first, write down the decision, run the smoke test afterwards,
and record the data impact.

## How a failed deployment is detected

- `docker compose … run --rm migrate` exits non-zero when a migration fails (step 6 of the runbook).
- `docker compose … up -d --wait` exits non-zero when any service fails to become healthy or the
  migration job fails (verified: exit 1).
- `/api/v1/health/ready` returns 503 when the database is unreachable (production).
- The smoke test fails on any broken route, header, auth flow, persistence or proxy limit.
