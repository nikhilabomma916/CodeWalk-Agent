// Starts the backend (FastAPI) and frontend (Next.js) dev servers together.
// Output is prefixed per service; Ctrl+C stops both.
import { spawn, spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";

const services = [
  {
    name: "backend ",
    color: "\x1b[36m",
    command: "uv",
    args: ["run", "python", "-m", "app"],
    cwd: join(root, "backend"),
  },
  {
    name: "frontend",
    color: "\x1b[35m",
    command: "npm",
    args: ["run", "dev"],
    cwd: join(root, "frontend"),
  },
];

const children = [];
let stopping = false;

function stopAll(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null) continue;
    // npm/next spawn grandchildren; on Windows only taskkill /T stops the whole tree.
    if (isWindows)
      spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    else child.kill("SIGTERM");
  }
  process.exitCode = code;
}

for (const service of services) {
  const options = {
    cwd: service.cwd,
    env: { ...process.env, FORCE_COLOR: "1" },
  };
  // On Windows a shell is needed to resolve npm.cmd; the command line is built
  // from the constant arguments above, never from user input.
  const child = isWindows
    ? spawn([service.command, ...service.args].join(" "), {
        ...options,
        shell: true,
      })
    : spawn(service.command, service.args, options);
  children.push(child);
  const prefix = `${service.color}[${service.name}]\x1b[0m `;
  const pipe = (stream, target) => {
    let buffered = "";
    stream.on("data", (chunk) => {
      buffered += chunk.toString();
      const lines = buffered.split(/\r?\n/);
      buffered = lines.pop() ?? "";
      for (const line of lines) target.write(prefix + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("error", (error) => {
    console.error(`${prefix}failed to start: ${error.message}`);
    stopAll(1);
  });
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(
        `${prefix}exited with code ${code}; stopping the other service.`,
      );
      stopAll(code ?? 1);
    }
  });
}

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
