// Tests for the regression runner itself (Module 14): `node --test scripts/runner.test.mjs`.
// They run real child processes; nothing is mocked.
import assert from "node:assert/strict";
import { test } from "node:test";

import { redact, runStep, secretValues, testCounts } from "./lib/runner.mjs";

const node = process.execPath;
const quiet = () => {};

test("a failing process makes the step FAIL with its real exit code", async () => {
  const result = await runStep({ command: node, args: ["-e", "process.exit(3)"], write: quiet });
  assert.equal(result.status, "FAIL");
  assert.equal(result.code, 3);
});

test("a succeeding process makes the step PASS", async () => {
  const result = await runStep({ command: node, args: ["-e", "console.log('ok')"], write: quiet });
  assert.equal(result.status, "PASS");
  assert.equal(result.code, 0);
  assert.match(result.output, /ok/);
});

test("a command that cannot start is FAIL, never PASS", async () => {
  const result = await runStep({ command: "codewalk-no-such-command-xyz", write: quiet });
  assert.equal(result.status, "FAIL");
});

test("arguments reach the process exactly: no splitting, quoting, or shell evaluation", async () => {
  const tricky = 'a b "c" ; echo INJECTED && exit 0 | $(whoami) %PATH%';
  const script = "process.exit(process.argv[1] === process.argv[2] ? 0 : 5)";
  const result = await runStep({ command: node, args: ["-e", script, tricky, tricky], write: quiet });
  assert.equal(result.status, "PASS");
  assert.doesNotMatch(result.output, /INJECTED/);
});

test("npm arguments a shell could split are refused before anything runs", async () => {
  if (process.platform !== "win32") return; // the shell is only used for npm on Windows
  await assert.rejects(async () => runStep({ command: "npm", args: ["run", "a b"], write: quiet }));
});

test("secrets never appear in captured or printed output", async () => {
  const env = {
    POSTGRES_PASSWORD: "Sup3r-Secret-Passw0rd",
    CODEWALK_TEST_DATABASE_URL: "postgresql+psycopg://codewalk:Sup3r-Secret-Passw0rd@db:5432/x_test",
    VOYAGE_API_KEY: "pa-fake-voyage-key-123456",
  };
  const secrets = secretValues(env);
  const printed = [];
  const script = [
    "console.log(process.env.CODEWALK_TEST_DATABASE_URL)",
    "console.error('password=' + process.env.POSTGRES_PASSWORD)",
    "console.log('key ' + process.env.VOYAGE_API_KEY)",
    "console.log('other://user:hunter2hunter2@example.invalid/path')",
  ].join(";");
  const result = await runStep({ command: node, args: ["-e", script], env, secrets, write: (s) => printed.push(s) });
  assert.equal(result.status, "PASS");
  const everything = result.output + printed.join("");
  for (const value of ["Sup3r-Secret-Passw0rd", "pa-fake-voyage-key-123456", "hunter2hunter2"])
    assert.ok(!everything.includes(value), `leaked ${value.slice(0, 3)}…`);
  assert.match(everything, /codewalk:\*\*\*@db:5432/);
  assert.match(everything, /password=\*\*\*/);
});

test("redact handles URLs and explicit values; secretValues ignores harmless keys", () => {
  assert.equal(redact("x postgresql://u:p4ssword@h/db y"), "x postgresql://u:***@h/db y");
  assert.equal(redact("token abcdef123", ["abcdef123"]), "token ***");
  assert.deepEqual(secretValues({ PATH: "/usr/bin", NODE_ENV: "test" }), []);
});

test("test counts are read from pytest, vitest, and node:test summaries", () => {
  assert.equal(testCounts("===== 412 passed, 3 skipped in 80.12s (0:01:20) ====="), "412 passed, 3 skipped");
  assert.equal(testCounts("      Tests  180 passed (180)"), "180 passed (180)");
  assert.equal(testCounts("# pass 8\n# fail 0\n"), "8 passed, 0 failed");
  assert.equal(testCounts("ℹ pass 7\nℹ fail 1\n"), "7 passed, 1 failed");
  assert.equal(testCounts("nothing here"), null);
});

test("an intentionally failing test file fails the step; a passing one passes", async () => {
  const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = mkdtempSync(join(tmpdir(), "codewalk-runner-"));
  try {
    const failing = join(dir, "failing.test.mjs");
    const passing = join(dir, "passing.test.mjs");
    writeFileSync(failing, 'import { test } from "node:test"; import assert from "node:assert"; test("x", () => assert.equal(1, 2));\n');
    writeFileSync(passing, 'import { test } from "node:test"; import assert from "node:assert"; test("x", () => assert.equal(1, 1));\n');
    const bad = await runStep({ command: node, args: ["--test", failing], write: quiet });
    assert.equal(bad.status, "FAIL");
    assert.notEqual(bad.code, 0);
    assert.equal(testCounts(bad.output), "0 passed, 1 failed");
    const good = await runStep({ command: node, args: ["--test", passing], write: quiet });
    assert.equal(good.status, "PASS");
    assert.equal(testCounts(good.output), "1 passed, 0 failed");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
