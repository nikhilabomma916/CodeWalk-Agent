// Module 22: migrate a managed (external) PostgreSQL database safely: preflight, verified backup,
// migration to head, drift check, preflight again. Never used for the local development database.
//
//   docker build -t codewalk-backend:local backend          # the image whose migrations are applied
//   CODEWALK_MIGRATION_DATABASE_URL=postgresql+psycopg://... node scripts/migrate-database.mjs
//   options: [--image codewalk-backend:local] [--network <docker network>] [--out-dir backups]
//            [--skip-backup]  (only when the provider's own point-in-time backup was taken)
//            [--allow-local-test]  (a local *_test database, for validating this script)
//
// The URL is read from the environment and handed to containers through the environment (`-e NAME`),
// never as an argument; output is redacted. The backup is pg_dump custom format from the pgvector
// image (client and server major versions must be compatible), verified with pg_restore --list, with
// a .sha256 file. backups/ is git-ignored: copy the dump somewhere safe.
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream, mkdirSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { PGVECTOR_IMAGE, option, run } from "./lib/db-container.mjs";
import { redact } from "./lib/runner.mjs";

const argv = process.argv.slice(2);
const image = option(argv, "--image", "codewalk-backend:local");
const network = option(argv, "--network", null);
const outDir = resolve(option(argv, "--out-dir", "backups"));
const url = process.env.CODEWALK_MIGRATION_DATABASE_URL ?? "";

function fail(message) {
  console.error(`\nmigrate-database: ${message}`);
  process.exit(1);
}

if (!url) fail("set CODEWALK_MIGRATION_DATABASE_URL (postgresql+psycopg://user:password@host/db?sslmode=require)");
let parsed;
try {
  parsed = new URL(url.replace(/^postgresql\+psycopg:/, "postgresql:"));
} catch {
  fail("CODEWALK_MIGRATION_DATABASE_URL is not a valid URL");
}
const database = decodeURIComponent(parsed.pathname.replace(/^\//, ""));
const local = ["localhost", "127.0.0.1", "[::1]", "postgres", "db", "host.docker.internal"].includes(parsed.hostname);
if (!/^[A-Za-z0-9_-]+$/.test(database)) fail("the URL names no valid database");
if (database === "codewalk") fail('refusing the development database "codewalk"');
if (local && !(argv.includes("--allow-local-test") && database.endsWith("_test"))) {
  fail("refusing a local database: this script is for managed databases (use --allow-local-test with a *_test database to validate it)");
}

const secrets = [url, decodeURIComponent(parsed.password)].filter((value) => value && value.length >= 4);
const say = (text) => process.stdout.write(redact(text, secrets));
const pgUrl = url.replace(/^postgresql\+psycopg:/, "postgresql:");
const net = network ? ["--network", network] : [];

async function backend(label, command) {
  say(`\n== ${label}\n`);
  const result = await run(
    "docker",
    ["run", "--rm", ...net, "-e", "CODEWALK_DATABASE_URL", "-e", "CODEWALK_ENV", image, ...command],
    {},
  ).catch((error) => ({ code: -1, stdout: "", stderr: String(error) }));
  say(result.stdout + result.stderr);
  if (result.code !== 0) fail(`${label} failed (exit ${result.code})`);
  return result.stdout;
}

// Containers inherit these through `-e NAME` (values never on a command line).
process.env.CODEWALK_DATABASE_URL = url;
process.env.CODEWALK_ENV = "development"; // only the database settings matter for migrations
process.env.PGURL = pgUrl;

{
  // Before migrating, a schema behind head is expected; an unreachable database or missing pgvector is not.
  say("\n== preflight before migration (database, pgvector)\n");
  const check = await run("docker", [
    "run", "--rm", ...net, "-e", "CODEWALK_DATABASE_URL", "-e", "CODEWALK_ENV", image,
    "python", "-m", "app.preflight", "--db-only",
  ]); // prettier-ignore
  say(check.stdout);
  if (/^FAIL\s+(database|pgvector|configuration)\b/m.test(check.stdout) || !/^PASS\s+database\b/m.test(check.stdout)) {
    fail("the database is not ready for migration (see the preflight above)");
  }
}
const before = (await backend("current revision", ["alembic", "current"])).trim();

if (!argv.includes("--skip-backup")) {
  mkdirSync(outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const file = join(outDir, `managed-${parsed.hostname.split(".")[0]}-${database}-${stamp}.dump`);
  say(`\n== backup (pg_dump, custom format) -> ${file}\n`);
  const dump = await run(
    "docker",
    ["run", "--rm", ...net, "-e", "PGURL", PGVECTOR_IMAGE, "sh", "-c", 'pg_dump -Fc --no-owner --no-privileges "$PGURL"'],
    { output: createWriteStream(file, { mode: 0o600 }) },
  );
  if (dump.code !== 0) fail(`pg_dump failed: ${redact(dump.stderr, secrets).trim()}`);
  const size = statSync(file).size;
  if (size === 0) fail("the backup is empty");
  const listed = await run("docker", ["run", "--rm", "-i", PGVECTOR_IMAGE, "pg_restore", "--list"], {
    input: createReadStream(file),
  });
  const entries = listed.stdout.split("\n").filter((line) => line && !line.startsWith(";")).length;
  if (listed.code !== 0 || entries === 0) fail("the backup could not be read back with pg_restore --list");
  const hash = createHash("sha256");
  await new Promise((done) => createReadStream(file).on("data", (c) => hash.update(c)).on("end", done));
  writeFileSync(`${file}.sha256`, `${hash.digest("hex")}  ${file.split(/[\\/]/).pop()}\n`);
  say(`backup verified: ${(size / 1024).toFixed(1)} KiB, ${entries} archive entries, sha256 written\n`);
} else {
  say("\n== backup skipped (--skip-backup): make sure the provider's point-in-time backup covers this moment\n");
}

await backend("migrate (alembic upgrade head)", ["alembic", "upgrade", "head"]);
await backend("drift check (alembic check)", ["alembic", "check"]);
const after = (await backend("revision after", ["alembic", "current"])).trim();
await backend("preflight after migration", ["python", "-m", "app.preflight", "--db-only"]);

say(`\nmigrated: ${before.split("\n").pop() || "(none)"} -> ${after.split("\n").pop()}\n`);
say(
  "Rollback: restore the backup into the same database (pg_restore --clean --if-exists --no-owner -d <url> <dump>)\n" +
    "or use the provider's point-in-time restore, then deploy the previous application version.\n",
);
