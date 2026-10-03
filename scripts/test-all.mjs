// Module 14: the complete automated regression suite in one command.
//
//   npm run test:all            backend + frontend on this machine
//   npm run test:all:docker     backend in the Linux test image next to the compose PostgreSQL
//   node scripts/test-all.mjs [--backend-docker] [--skip-backend] [--skip-frontend] [--skip-build]
//                             [--log <file>]
//
// Steps: runner self-test; backend lint, format, types, tests (PostgreSQL tests run when a *_test
// database is configured, otherwise pytest reports them as skipped), migration upgrade + drift
// check; frontend lint, format, types, tests, production build.
//
// Trust rules (see scripts/lib/runner.mjs and scripts/runner.test.mjs): commands run without a
// shell (npm excepted on Windows, with shell-safe arguments); a step passes only when its process
// exits 0; all output is redacted before it is printed or logged; database credentials reach
// processes and containers only through environment variables, never through arguments.
import { createWriteStream, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { runStep, secretValues, testCounts } from "./lib/runner.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const flags = new Set(argv);
const logIndex = argv.indexOf("--log");
const logFile = logIndex >= 0 ? argv[logIndex + 1] : null;

/** Minimal .env reader. Values are used only as environment variables and never printed. */
function dotenv() {
  const file = join(root, ".env");
  const values = {};
  if (!existsSync(file)) return values;
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = /^([A-Z0-9_]+)=(.*)$/.exec(line.trim());
    if (match) values[match[1]] = match[2];
  }
  return values;
}

const fileEnv = dotenv();
const config = { ...fileEnv, ...process.env };
const secrets = secretValues(config);
const log = logFile ? createWriteStream(logFile, { flags: "w" }) : null;
const write = (text) => {
  process.stdout.write(text);
  log?.write(text);
};
const results = [];

async function step(name, command, args, options = {}) {
  write(`\n\x1b[1m▶ ${name}\x1b[0m\n`);
  const result = await runStep({ command, args, secrets, write, ...options });
  results.push({ name, status: result.status, seconds: result.seconds.toFixed(1), counts: testCounts(result.output) });
  return result.status === "PASS";
}

function skip(name, reason) {
  results.push({ name, status: "SKIPPED", seconds: "-", reason });
}

const testDatabaseUrl = () => {
  const url = config.CODEWALK_TEST_DATABASE_URL;
  return url && /_test$/.test(url.split("/").pop() ?? "") ? url : null;
};

await step("runner self-test (node --test)", process.execPath, ["--test", join(root, "scripts", "runner.test.mjs")]);

// --- backend -----------------------------------------------------------------------------
if (!flags.has("--skip-backend")) {
  if (flags.has("--backend-docker")) {
    const password = config.POSTGRES_PASSWORD;
    if (!password) {
      write("POSTGRES_PASSWORD is not set (see .env.example); the database container cannot be used.\n");
      results.push({ name: "backend in Docker", status: "FAIL", seconds: "-", reason: "POSTGRES_PASSWORD missing" });
    } else {
      const user = config.POSTGRES_USER || "codewalk";
      const testDb = `${config.POSTGRES_DB || "codewalk"}_test`;
      // The URL is handed to Docker through the environment (`-e NAME` copies the value), so it
      // never appears in a command line; the runner redacts it from any output as well.
      const databaseEnv = {
        CODEWALK_TEST_DATABASE_URL: `postgresql+psycopg://${user}:${password}@postgres:5432/${testDb}`,
      };
      databaseEnv.CODEWALK_DATABASE_URL = databaseEnv.CODEWALK_TEST_DATABASE_URL;
      const image = "codewalk-backend-test:local";
      const docker = (name, passEnv, command) =>
        step(
          name,
          "docker",
          ["run", "--rm", "--network", "codewalk_default", ...passEnv.flatMap((key) => ["-e", key]), image, ...command],
          { env: databaseEnv },
        );
      const up = await step("database container (compose postgres, pgvector)", "docker", [
        "compose",
        "up",
        "-d",
        "--wait",
        "postgres",
      ]);
      const built =
        up &&
        (await step("backend test image (docker build)", "docker", [
          "build",
          "-q",
          "-t",
          image,
          "-f",
          "docker/backend-test/Dockerfile",
          "backend",
        ]));
      if (built) {
        await docker("backend lint (ruff)", [], ["uv", "run", "ruff", "check", "app", "tests"]);
        await docker("backend format (ruff format --check)", [], ["uv", "run", "ruff", "format", "--check", "app", "tests"]);
        await docker("backend types (mypy --strict)", [], ["uv", "run", "mypy"]);
        // Only the test database URL: an application CODEWALK_DATABASE_URL would change what some tests expect.
        await docker("backend tests (pytest, PostgreSQL + pgvector)", ["CODEWALK_TEST_DATABASE_URL"], [
          "uv",
          "run",
          "pytest",
          "-p",
          "no:cacheprovider",
          "-ra",
        ]);
        (await docker("migrations (alembic upgrade head)", ["CODEWALK_DATABASE_URL"], ["uv", "run", "alembic", "upgrade", "head"])) &&
          (await docker("migration drift (alembic check)", ["CODEWALK_DATABASE_URL"], ["uv", "run", "alembic", "check"]));
      } else {
        skip("backend checks in Docker", "the database container or the test image is not available");
      }
    }
  } else {
    const backend = { cwd: join(root, "backend") };
    const url = testDatabaseUrl();
    const testsEnv = url ? { CODEWALK_TEST_DATABASE_URL: url } : {};
    await step("backend lint (ruff)", "uv", ["run", "ruff", "check", "app", "tests"], backend);
    await step("backend format (ruff format --check)", "uv", ["run", "ruff", "format", "--check", "app", "tests"], backend);
    await step("backend types (mypy --strict)", "uv", ["run", "mypy"], backend);
    await step("backend tests (pytest)", "uv", ["run", "pytest", "-p", "no:cacheprovider", "-ra"], { ...backend, env: testsEnv });
    if (url) {
      const migrate = { ...backend, env: { CODEWALK_DATABASE_URL: url } };
      (await step("migrations (alembic upgrade head)", "uv", ["run", "alembic", "upgrade", "head"], migrate)) &&
        (await step("migration drift (alembic check)", "uv", ["run", "alembic", "check"], migrate));
    } else {
      skip("migrations (alembic upgrade head + check)", "CODEWALK_TEST_DATABASE_URL (*_test) is not set");
    }
  }
}

// --- frontend ----------------------------------------------------------------------------
if (!flags.has("--skip-frontend")) {
  const npm = (script) => ["--prefix", "frontend", "run", script];
  await step("frontend lint (eslint)", "npm", npm("lint"), { cwd: root });
  await step("frontend format (prettier --check)", "npm", npm("format:check"), { cwd: root });
  await step("frontend types (tsc)", "npm", npm("typecheck"), { cwd: root });
  await step("frontend tests (vitest)", "npm", npm("test"), { cwd: root });
  if (flags.has("--skip-build")) skip("frontend production build", "--skip-build");
  else await step("frontend production build", "npm", npm("build"), { cwd: root });
}

// --- summary -----------------------------------------------------------------------------
const width = Math.max(...results.map((r) => r.name.length));
write("\n\x1b[1mRegression suite summary\x1b[0m\n");
for (const r of results) {
  const color = r.status === "PASS" ? "\x1b[32m" : r.status === "FAIL" ? "\x1b[31m" : "\x1b[33m";
  const extra = r.counts ? `  [${r.counts}]` : r.reason ? `  (${r.reason})` : "";
  write(`  ${color}${r.status.padEnd(7)}\x1b[0m ${r.name.padEnd(width)}  ${String(r.seconds).padStart(6)}s${extra}\n`);
}
write(
  "\nSKIPPED tests (pytest -ra lists each with its reason) did not run; skipped is not passed.\n",
);
const failed = results.filter((r) => r.status === "FAIL").length;
write(failed ? `\n${failed} step(s) FAILED.\n` : "\nAll steps passed.\n");
log?.end();
process.exitCode = failed ? 1 : 0;
