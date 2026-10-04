# Database backup and restore

The database holds every account, project, file version, analysis, embedding and agent record.
Backups use PostgreSQL's own tools (`pg_dump` custom format) through two scripts that never print a
password and never overwrite a database.

## Back up

```bash
npm run db:backup -- --project codewalk-prod --service db        # production stack
npm run db:backup -- --project codewalk --service postgres        # development database
# options: --database <name> (default: the container's POSTGRES_DB), --out-dir <dir> (default backups/)
```

What it does (`scripts/backup-db.mjs`):

1. finds the running database container by its compose labels;
2. runs `pg_dump --format=custom --compress=6 --no-owner` **inside** the container over its local
   socket (no password needed or printed) and streams the dump to the host:
   `backups/<project>-<database>-<UTC time>.dump` (mode 600). Nothing is stored inside the container;
3. verifies the archive with `pg_restore --list` (in a throwaway container) and checks that the
   schema revision table is present;
4. writes `<file>.sha256`.

`backups/` and `*.dump` are git-ignored. **Copy backups off the host** (object storage, another
machine) and encrypt them at rest: they contain user data and password hashes.

Schedule it, for example daily with cron, keeping 14 days:

```cron
15 3 * * * cd /opt/codewalk && npm run -s db:backup -- --project codewalk-prod --service db >> /var/log/codewalk-backup.log 2>&1 && find backups -name '*.dump*' -mtime +14 -delete
```

Always take a backup immediately before deploying a release that contains migrations.

## Verify a backup (safe, routine)

```bash
npm run db:restore -- --file backups/codewalk-prod-codewalk-20261003T120000Z.dump
```

Restores into a **disposable** PostgreSQL + pgvector container (random password, no published ports,
deleted afterwards) and reports the schema revision, the pgvector extension and row counts of the main
tables. It checks the `.sha256` file first and refuses a damaged or modified backup. Run it after every
scheduled backup, or at least weekly; a backup that has never been restored is not a backup.

## Restore for real

The script never drops, truncates or overwrites a database. A real restore goes into a **new**
database next to the live one, then the application is switched to it deliberately:

```bash
# 1. Restore into a new database inside the running db container
npm run db:restore -- --file <dump> --project codewalk-prod --service db --new-database codewalk_restored_20261003

# 2. Inspect it (row counts are printed; query it if needed)
docker compose -f docker-compose.prod.yml --env-file .env.production exec db psql -U codewalk -d codewalk_restored_20261003

# 3. Switch the application: set POSTGRES_DB=codewalk_restored_20261003 in .env.production, then
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait
```

Step 3 recreates the backend and runs the migration job against the restored database (a no-op when
the dump is at the current schema revision; it upgrades an older dump). The previous database stays
untouched, so switching back is the same edit in reverse. Drop the old database only after you are
certain, manually, with `DROP DATABASE`.

The script refuses: restoring over the live database name, restoring into an existing database, and
backups whose checksum does not match.

## Disaster recovery (host lost)

1. Provision a new host and follow [production-deployment.md](production-deployment.md) up to
   `config -q`.
2. Start only the database: `docker compose … up -d --wait db`.
3. Restore into a new database (above) and set `POSTGRES_DB` to it.
4. `docker compose … up -d --wait`, then run the smoke test.

## Tested

On 2026-10-03 (local Docker Desktop): a backup of the production-like test stack (37 KiB) and of the
development database (452 KiB; 58 users, 25 projects, 655 files) were each restored into a disposable
container with identical row counts; restoring into a new database, the refusal to restore over the
live or an existing database, and the checksum refusal of a modified file were all exercised.
