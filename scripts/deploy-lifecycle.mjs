// Module 15: production-stack lifecycle test and timing measurement.
//
//   npm run test:deploy                       (node scripts/deploy-lifecycle.mjs)
//   node scripts/deploy-lifecycle.mjs [--project codewalk-smoke] [--port 8088] [--env-file <file>]
//                                     [--no-build] [--keep] [--remove-volume] [--log <file>]
//
// Steps: compose config -> build -> up (wait for health) -> smoke test (stores a persistence
// marker) -> stop -> start (wait for health) -> smoke test (verifies the marker survived) -> down.
// Prints measured timings (build, database readiness, migration, backend/frontend/proxy readiness,
// whole-stack readiness, restart readiness). Nothing is estimated.
//
// Safety: runs as its own compose project (default "codewalk-smoke") with its own volume; it never
// touches the development database (project "codewalk"). Without --env-file it generates throwaway
// secrets into a private temporary file that is deleted afterwards. The volume is removed only with
// --remove-volume, and only for projects named codewalk-smoke*. Output is redacted.
import { randomBytes } from "node:crypto";
import { createWriteStream, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { runStep, testCounts } from "./lib/runner.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const option = (name, fallback) => {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : fallback;
};
const flag = (name) => argv.includes(name);

const project = option("--project", "codewalk-smoke");
const port = option("--port", "8088");
const logFile = option("--log", null);
if (!/^[a-z0-9][a-z0-9_-]*$/.test(project) || project === "codewalk") {
  console.error(`refusing project name ${JSON.stringify(project)} (the development project is "codewalk")`);
  process.exit(2);
}

const work = mkdtempSync(join(tmpdir(), "codewalk-lifecycle-"));
const stateFile = join(work, "smoke-state.json");
let envFile = option("--env-file", null);
if (!envFile) {
  envFile = join(work, "lifecycle.env");
  const lines = [
    `POSTGRES_PASSWORD=${randomBytes(32).toString("base64url")}`,
    `CODEWALK_SECRET_KEY=${randomBytes(48).toString("base64url")}`,
    "CODEWALK_PROXY_TLS=off",
    "CODEWALK_BIND_ADDRESS=127.0.0.1",
    `CODEWALK_HTTP_PORT=${port}`,
    `CODEWALK_HTTPS_PORT=${Number(port) + 1}`,
  ];
  writeFileSync(envFile, `${lines.join("\n")}\n`, { mode: 0o600 });
}
const secrets = readFileSync(envFile, "utf8")
  .split(/\r?\n/)
  .map((line) => /^[A-Z0-9_]*(PASSWORD|SECRET|KEY|TOKEN)[A-Z0-9_]*=(.+)$/.exec(line.trim())?.[2])
  .filter((value) => value && value.length >= 8);

const log = logFile ? createWriteStream(logFile, { flags: "w" }) : null;
const write = (text) => {
  process.stdout.write(text);
  log?.write(text);
};
const compose = ["compose", "-f", join(root, "docker-compose.prod.yml"), "-p", project, "--env-file", envFile];
const results = [];
const timings = [];

async function step(name, command, args, options = {}) {
  write(`\n\x1b[1m▶ ${name}\x1b[0m\n`);
  const result = await runStep({ command, args, cwd: root, secrets, write, ...options });
  results.push({ name, status: result.status, seconds: result.seconds, counts: testCounts(result.output) });
  if (result.status !== "PASS") throw new Error(`${name} failed (exit ${result.code})`);
  return result;
}

async function quiet(command, args) {
  return runStep({ command, args, cwd: root, secrets, write: () => {} });
}

/** Seconds from a container's start to its first passing health check (or exit, for jobs). */
async function readiness(service) {
  const ids = (await quiet("docker", [...compose, "ps", "-a", "-q", service])).output.trim();
  if (!ids) return null;
  const inspect = JSON.parse((await quiet("docker", ["inspect", ids.split(/\s+/)[0]])).output)[0];
  const started = Date.parse(inspect.State.StartedAt);
  if (!inspect.State.Health || inspect.State.Status === "exited") {
    const finished = Date.parse(inspect.State.FinishedAt);
    return finished > started ? (finished - started) / 1000 : null;
  }
  const passing = inspect.State.Health.Log.find((entry) => entry.ExitCode === 0);
  return passing ? (Date.parse(passing.End) - started) / 1000 : null;
}

async function proxyRequests() {
  const result = await quiet("docker", [...compose, "logs", "--no-log-prefix", "proxy"]);
  return result.output.split("\n").filter((line) => / rid=[0-9a-f]{32} /.test(line)).length;
}

async function smoke(label) {
  const before = await proxyRequests();
  await step(label, "uv", ["--directory", "backend", "run", "pytest", "-p", "no:cacheprovider", "-v", "../tests/deployment/test_smoke.py"], {
    env: { CODEWALK_SMOKE_URL: `http://127.0.0.1:${port}`, CODEWALK_SMOKE_STATE: stateFile },
  });
  const after = await proxyRequests();
  write(`proxy access-log lines during "${label}": ${after - before}\n`);
  if (after - before < 10) throw new Error(`${label}: only ${after - before} requests reached the proxy`);
}

let failed = null;
try {
  await step("compose configuration", "docker", [...compose, "config", "-q"]);
  if (!flag("--no-build")) {
    const build = await step("build images", "docker", [...compose, "build"]);
    timings.push(["image build (all images)", build.seconds]);
  }
  const up = await step("start stack and wait for health", "docker", [...compose, "up", "-d", "--wait", "--wait-timeout", "240"]);
  timings.push(["stack ready (up --wait, cold start)", up.seconds]);
  for (const service of ["db", "migrate", "backend", "frontend", "proxy"]) {
    const seconds = await readiness(service);
    timings.push([service === "migrate" ? "migration job (start -> exit 0)" : `${service} start -> healthy`, seconds]);
  }
  await smoke("smoke test (first start)");
  await step("stop stack", "docker", [...compose, "stop"]);
  const restart = await step("start again and wait for health", "docker", [...compose, "up", "-d", "--wait", "--wait-timeout", "240"]);
  timings.push(["stack ready after restart (same volume)", restart.seconds]);
  if (!existsSync(stateFile)) throw new Error("the first smoke run did not record its persistence marker");
  await smoke("smoke test after restart (persistence)");
} catch (error) {
  failed = error;
  write(`\n\x1b[31m${error.message}\x1b[0m\n`);
  const logs = await quiet("docker", [...compose, "logs", "--tail", "40"]);
  write(logs.output);
} finally {
  if (!flag("--keep")) {
    const removeVolume = flag("--remove-volume") && project.startsWith("codewalk-smoke");
    await step("shut down", "docker", [...compose, "down", ...(removeVolume ? ["--volumes"] : [])]).catch(() => {});
  }
  rmSync(work, { recursive: true, force: true });
}

write("\n\x1b[1mLifecycle summary\x1b[0m\n");
for (const r of results) {
  const color = r.status === "PASS" ? "\x1b[32m" : "\x1b[31m";
  write(`  ${color}${r.status.padEnd(5)}\x1b[0m ${r.name.padEnd(44)} ${r.seconds.toFixed(1).padStart(6)}s  ${r.counts ? `[${r.counts}]` : ""}\n`);
}
write("\n\x1b[1mMeasured timings\x1b[0m\n");
for (const [name, seconds] of timings) {
  write(`  ${name.padEnd(44)} ${seconds === null ? "n/a" : `${seconds.toFixed(1)}s`}\n`);
}
log?.end();
process.exitCode = failed ? 1 : 0;
