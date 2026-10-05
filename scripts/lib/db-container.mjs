// Helpers shared by the database backup and restore scripts (Module 15).
// Commands run without a shell; no database password is ever passed as an argument or printed.
import { spawn } from "node:child_process";

/** Runs a command and resolves with { code, stdout, stderr } (stdout optionally piped to a stream). */
export function run(command, args, { input, output } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: [input ? "pipe" : "ignore", "pipe", "pipe"], windowsHide: true });
    let stdout = "";
    let stderr = "";
    if (output) child.stdout.pipe(output);
    else child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    if (input) input.pipe(child.stdin);
    child.on("error", (error) => resolve({ code: -1, stdout, stderr: String(error) }));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

/** The running container of a compose service, found by compose labels (no compose file needed). */
export async function serviceContainer(project, service) {
  const result = await run("docker", [
    "ps", "-q",
    "--filter", `label=com.docker.compose.project=${project}`,
    "--filter", `label=com.docker.compose.service=${service}`,
  ]); // prettier-ignore
  const ids = result.stdout.trim().split(/\s+/).filter(Boolean);
  if (result.code !== 0 || ids.length !== 1) {
    throw new Error(`expected one running container for ${project}/${service}, found ${ids.length}`);
  }
  return ids[0];
}

/** Runs psql inside a container as the container's own superuser (local socket, no password). */
export async function psql(container, database, sql) {
  const result = await run("docker", [
    "exec", container, "sh", "-c", 'psql -v ON_ERROR_STOP=1 -X -At -U "$POSTGRES_USER" -d "$1" -c "$2"', "psql", database, sql,
  ]); // prettier-ignore
  if (result.code !== 0) throw new Error(`psql failed: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

export const PGVECTOR_IMAGE = "pgvector/pgvector:pg17-bookworm";

export function option(argv, name, fallback = null) {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : fallback;
}
