// Module 15: PostgreSQL backup of a running CodeWalk database container.
//
//   npm run db:backup -- --project codewalk-prod --service db          (production stack)
//   npm run db:backup -- --project codewalk --service postgres          (development database)
//   options: [--database <name>] [--out-dir backups]
//
// Writes backups/<project>-<database>-<UTC timestamp>.dump (pg_dump custom format, compressed) and a
// .sha256 file next to it, then verifies the archive with pg_restore --list. The dump streams from
// the container to the host: nothing is stored inside the database container. pg_dump runs inside
// the container over its local socket, so no password is used or printed. backups/ is git-ignored;
// copy backups off the host (see docs/deployment/database-backup-restore.md).
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream, mkdirSync, statSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

import { PGVECTOR_IMAGE, option, psql, run, serviceContainer } from "./lib/db-container.mjs";

const argv = process.argv.slice(2);
const project = option(argv, "--project", "codewalk-prod");
const service = option(argv, "--service", project === "codewalk" ? "postgres" : "db");
const outDir = resolve(option(argv, "--out-dir", "backups"));

try {
  const container = await serviceContainer(project, service);
  const database = option(argv, "--database") ?? (await run("docker", ["exec", container, "printenv", "POSTGRES_DB"])).stdout.trim();
  if (!/^[A-Za-z0-9_]+$/.test(database)) throw new Error(`invalid database name ${JSON.stringify(database)}`);
  const revision = await psql(container, database, "SELECT version_num FROM alembic_version");

  mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const file = join(outDir, `${project}-${database}-${stamp}.dump`);
  const out = createWriteStream(file, { flags: "wx", mode: 0o600 });
  const started = Date.now();
  const dump = await run(
    "docker",
    ["exec", container, "sh", "-c", 'pg_dump --format=custom --compress=6 --no-owner -U "$POSTGRES_USER" -d "$1"', "pg_dump", database],
    { output: out },
  );
  await new Promise((done) => out.end(done));
  if (dump.code !== 0) throw new Error(`pg_dump failed: ${dump.stderr.trim()}`);

  // Verify the archive is readable and complete (table of contents, schema and data entries).
  const list = await run("docker", ["run", "--rm", "-i", PGVECTOR_IMAGE, "pg_restore", "--list"], { input: createReadStream(file) });
  if (list.code !== 0) throw new Error(`pg_restore --list failed: ${list.stderr.trim()}`);
  const toc = list.stdout.split("\n").filter((line) => line && !line.startsWith(";"));
  const tables = toc.filter((line) => / TABLE DATA /.test(line)).length;
  if (!toc.some((line) => / TABLE DATA public alembic_version /.test(line))) {
    throw new Error("backup verification failed: alembic_version data is missing");
  }

  const hash = createHash("sha256");
  await new Promise((done, fail) => createReadStream(file).on("data", (c) => hash.update(c)).on("end", done).on("error", fail));
  const digest = hash.digest("hex");
  writeFileSync(`${file}.sha256`, `${digest}  ${basename(file)}\n`);

  console.log(`backup:    ${file}`);
  console.log(`size:      ${(statSync(file).size / 1024).toFixed(1)} KiB, ${((Date.now() - started) / 1000).toFixed(1)} s`);
  console.log(`database:  ${database} (schema revision ${revision})`);
  console.log(`verified:  ${toc.length} archive entries, ${tables} tables with data`);
  console.log(`sha256:    ${digest}`);
} catch (error) {
  console.error(`backup failed: ${error.message}`);
  process.exitCode = 1;
}
