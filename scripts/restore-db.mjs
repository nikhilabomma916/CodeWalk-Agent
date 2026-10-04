// Module 15: restore a CodeWalk PostgreSQL backup, safely.
//
// 1. Verify (default): restore into a disposable PostgreSQL + pgvector container that is deleted
//    afterwards, then check the schema revision, the pgvector extension and row counts.
//      npm run db:restore -- --file backups/codewalk-prod-codewalk-20261003T120000Z.dump
//
// 2. Restore into a NEW database next to the live one (never over an existing database):
//      npm run db:restore -- --file <dump> --project codewalk-prod --service db --new-database codewalk_restored
//    Switching the application to it is a separate, deliberate step (POSTGRES_DB / the database
//    URL; see docs/deployment/database-backup-restore.md). This script never drops, overwrites or
//    truncates a database.
//
// No password is printed: the disposable container gets a random one through its environment, and
// restores into a running stack use the container's local socket.
import { randomBytes } from "node:crypto";
import { createReadStream, existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";

import { PGVECTOR_IMAGE, option, psql, run, serviceContainer } from "./lib/db-container.mjs";

const argv = process.argv.slice(2);
const file = option(argv, "--file");
const project = option(argv, "--project");
const newDatabase = option(argv, "--new-database");
const CHECK_TABLES = ["users", "projects", "files", "file_versions", "analyses", "code_chunks", "agent_runs", "agent_actions"];

async function verifyChecksum() {
  const sumFile = `${file}.sha256`;
  if (!existsSync(sumFile)) return "no .sha256 file next to the backup (not checked)";
  const expected = readFileSync(sumFile, "utf8").split(/\s+/)[0];
  const hash = createHash("sha256");
  await new Promise((done, fail) => createReadStream(file).on("data", (c) => hash.update(c)).on("end", done).on("error", fail));
  if (hash.digest("hex") !== expected) throw new Error("checksum mismatch: the backup file is damaged or was changed");
  return "sha256 matches";
}

async function restoreInto(container, database) {
  const restore = await run(
    "docker",
    ["exec", "-i", container, "sh", "-c", 'pg_restore --no-owner --exit-on-error -U "$POSTGRES_USER" -d "$1"', "pg_restore", database],
    { input: createReadStream(file) },
  );
  if (restore.code !== 0) throw new Error(`pg_restore failed: ${restore.stderr.trim()}`);
}

async function report(container, database) {
  const revision = await psql(container, database, "SELECT version_num FROM alembic_version");
  const vector = await psql(container, database, "SELECT extversion FROM pg_extension WHERE extname = 'vector'");
  console.log(`schema revision: ${revision}`);
  console.log(`pgvector:        ${vector || "MISSING"}`);
  if (!vector) throw new Error("the restored database has no pgvector extension");
  for (const table of CHECK_TABLES) {
    const exists = await psql(container, database, `SELECT to_regclass('public.${table}') IS NOT NULL`);
    const count = exists === "t" ? await psql(container, database, `SELECT count(*) FROM ${table}`) : "missing";
    console.log(`  ${table.padEnd(16)} ${count}`);
  }
}

async function verifyInDisposableContainer() {
  const name = `codewalk-restore-verify-${randomBytes(4).toString("hex")}`;
  const started = await run("docker", [
    "run", "-d", "--rm", "--name", name,
    "-e", "POSTGRES_USER=codewalk", "-e", "POSTGRES_DB=codewalk_verify",
    "-e", `POSTGRES_PASSWORD=${randomBytes(24).toString("base64url")}`,
    PGVECTOR_IMAGE,
  ]); // prettier-ignore
  if (started.code !== 0) throw new Error(`could not start the verification container: ${started.stderr.trim()}`);
  try {
    for (let attempt = 0; ; attempt++) {
      const ready = await run("docker", ["exec", name, "pg_isready", "-U", "codewalk", "-d", "codewalk_verify"]);
      // The image restarts the server once after initialisation: require a working query too.
      if (ready.code === 0 && (await run("docker", ["exec", name, "psql", "-U", "codewalk", "-d", "codewalk_verify", "-c", "SELECT 1"])).code === 0) break;
      if (attempt > 60) throw new Error("verification database did not become ready");
      await new Promise((r) => setTimeout(r, 1000));
    }
    await new Promise((r) => setTimeout(r, 2000));
    await restoreInto(name, "codewalk_verify");
    console.log(`restored into disposable container ${name} (no ports published)`);
    await report(name, "codewalk_verify");
  } finally {
    await run("docker", ["rm", "-f", name]);
    console.log("disposable container removed");
  }
}

async function restoreAsNewDatabase() {
  if (!/^[a-z_][a-z0-9_]{0,62}$/.test(newDatabase)) throw new Error("--new-database must be a lowercase identifier");
  const service = option(argv, "--service", project === "codewalk" ? "postgres" : "db");
  const container = await serviceContainer(project, service);
  const live = (await run("docker", ["exec", container, "printenv", "POSTGRES_DB"])).stdout.trim();
  if (newDatabase === live) throw new Error(`refusing to restore over the live database ${live}`);
  const exists = await psql(container, "postgres", `SELECT 1 FROM pg_database WHERE datname = '${newDatabase}'`);
  if (exists) throw new Error(`database ${newDatabase} already exists; choose a new name (nothing is overwritten)`);
  await psql(container, "postgres", `CREATE DATABASE ${newDatabase}`);
  await restoreInto(container, newDatabase);
  console.log(`restored into new database ${newDatabase} in ${project}/${service} (live database ${live} untouched)`);
  await report(container, newDatabase);
}

try {
  if (!file || !existsSync(file)) throw new Error("--file <backup.dump> is required and must exist");
  console.log(`backup:   ${file}`);
  console.log(`checksum: ${await verifyChecksum()}`);
  if (newDatabase) {
    if (!project) throw new Error("--new-database needs --project (and optionally --service)");
    await restoreAsNewDatabase();
  } else {
    await verifyInDisposableContainer();
  }
  console.log("restore: OK");
} catch (error) {
  console.error(`restore failed: ${error.message}`);
  process.exitCode = 1;
}
