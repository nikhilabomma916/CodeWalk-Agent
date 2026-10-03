// Process runner for the regression suite (Module 14).
//
// Guarantees, each covered by scripts/runner.test.mjs:
// - Commands run directly (no shell), so arguments reach the process exactly as given.
//   Only `npm` uses a shell on Windows (npm.cmd needs one); its arguments must be shell-safe.
// - A step is PASS only when its process ran and exited with status 0. A spawn error, a
//   signal, or any other exit status is FAIL.
// - Output is captured line by line and redacted (credentials in URLs and known secret
//   values) before it is printed or written to a log. Nothing dumps the environment.
// - Secrets reach child processes only through environment variables, never arguments.
import { spawn } from "node:child_process";

const SECRET_KEY = /PASSWORD|SECRET|API_KEY|TOKEN|DATABASE_URL|PRIVATE_KEY/i;
const URL_CREDENTIALS = /([a-z][a-z0-9+.-]*:\/\/)([^\s:/@]+):([^\s@/]+)@/gi;
const SAFE_SHELL_ARG = /^[A-Za-z0-9_./:=@%+,-]+$/;

/** Secret values from an environment: sensitive keys' values, plus passwords inside URLs. */
export function secretValues(env) {
  const values = new Set();
  for (const [key, value] of Object.entries(env)) {
    if (!value || typeof value !== "string") continue;
    if (SECRET_KEY.test(key) && value.length >= 6) values.add(value);
    for (const match of value.matchAll(URL_CREDENTIALS)) if (match[3].length >= 4) values.add(match[3]);
  }
  return [...values].sort((a, b) => b.length - a.length);
}

/** Removes credentials from text: `scheme://user:pass@` and every known secret value. */
export function redact(text, secrets = []) {
  let out = text.replace(URL_CREDENTIALS, "$1$2:***@");
  for (const secret of secrets) if (secret) out = out.split(secret).join("***");
  return out;
}

/** Test counts from pytest / vitest output, for the summary (null when not found). */
export function testCounts(output) {
  const plain = output.replace(/\x1b\[[0-9;]*m/g, "");
  const pytest = /^=+ (.*\b(?:passed|failed|error|skipped)\b.*) in [\d.]+s/m.exec(plain);
  if (pytest) return pytest[1];
  const vitest = /^\s*Tests\s+(.+?)\s*$/m.exec(plain);
  if (vitest) return vitest[1];
  const node = /^(?:#|ℹ) pass (\d+)[\s\S]*?^(?:#|ℹ) fail (\d+)/m.exec(plain);
  if (node) return `${node[1]} passed, ${node[2]} failed`;
  return null;
}

function assertShellSafe(args) {
  for (const arg of args)
    if (!SAFE_SHELL_ARG.test(arg)) throw new Error(`Refusing to pass a shell-unsafe argument to npm: ${arg}`);
}

/**
 * Runs one command and resolves { status: "PASS" | "FAIL", code, output, seconds }.
 * `output` is the redacted combined output. `write` receives redacted lines (default: stdout).
 */
export function runStep({ command, args = [], cwd, env = {}, secrets = [], write = (s) => process.stdout.write(s) }) {
  const isWindows = process.platform === "win32";
  const useShell = isWindows && command === "npm";
  if (useShell) assertShellSafe(args);
  const started = Date.now();
  // Inherited NODE_TEST_CONTEXT makes a child `node --test` report through its parent's test
  // runner and exit 0 even when its tests fail (a false PASS): every step runs without it.
  // A variable given as `undefined` in `env` is removed from the child's environment.
  const childEnv = { ...process.env, ...env };
  delete childEnv.NODE_TEST_CONTEXT;
  for (const [key, value] of Object.entries(env)) if (value === undefined) delete childEnv[key];
  return new Promise((resolve) => {
    let output = "";
    let child;
    try {
      child = spawn(command, args, {
        cwd,
        env: childEnv,
        shell: useShell,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
    } catch (error) {
      const line = redact(`failed to start ${command}: ${error.message}\n`, secrets);
      write(line);
      resolve({ status: "FAIL", code: null, output: line, seconds: 0 });
      return;
    }
    const pending = { stdout: "", stderr: "" };
    const flush = (stream, final = false) => {
      const lines = pending[stream].split(/(?<=\n)/);
      pending[stream] = final ? "" : lines.pop() ?? "";
      for (const line of lines) {
        if (!line) continue;
        const safe = redact(line, secrets);
        output += safe;
        write(safe);
      }
    };
    for (const stream of ["stdout", "stderr"]) {
      child[stream].setEncoding("utf8");
      child[stream].on("data", (chunk) => {
        pending[stream] += chunk;
        flush(stream);
      });
    }
    let spawnError = null;
    child.on("error", (error) => {
      spawnError = error;
    });
    child.on("close", (code, signal) => {
      flush("stdout", true);
      flush("stderr", true);
      if (spawnError) {
        const line = redact(`failed to start ${command}: ${spawnError.message}\n`, secrets);
        output += line;
        write(line);
      }
      const ok = !spawnError && signal === null && code === 0;
      resolve({ status: ok ? "PASS" : "FAIL", code, output, seconds: (Date.now() - started) / 1000 });
    });
  });
}
