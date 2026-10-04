import { describe, expect, it, vi } from "vitest";

import { applyProposedChanges, decideAgentAction, runAgent, type ProposedChange } from "./agent";
import { createApiClient } from "./client";

import type { Diagnostic } from "@/types/diagnostics";

const change = (overrides: Partial<ProposedChange>): ProposedChange => ({
  file_path: "a.py",
  start_line: 1,
  start_column: 1,
  end_line: 1,
  end_column: 1,
  original_text: "",
  replacement_text: "",
  ...overrides,
});

describe("applyProposedChanges", () => {
  const content = "def f(items):\n    for i in items:\n        total += i\n    return total\n";

  it("applies exact ranges in any order", () => {
    const result = applyProposedChanges(content, [
      change({
        start_line: 4,
        end_line: 4,
        start_column: 12,
        end_column: 17,
        original_text: "total",
        replacement_text: "sum_",
      }),
      change({
        start_line: 2,
        end_line: 3,
        original_text: "    for i in items:\n",
        replacement_text: "    total = 0\n    for i in items:\n",
      }),
    ]);
    expect(result).toBe(
      "def f(items):\n    total = 0\n    for i in items:\n        total += i\n    return sum_\n",
    );
  });

  it("handles CRLF files", () => {
    const crlf = "a = 1\r\nb = 2\r\n";
    expect(
      applyProposedChanges(crlf, [
        change({
          start_line: 2,
          end_line: 2,
          end_column: 6,
          original_text: "b = 2",
          replacement_text: "b = 3",
        }),
      ]),
    ).toBe("a = 1\r\nb = 3\r\n");
  });

  it("refuses stale proposals instead of guessing", () => {
    expect(
      applyProposedChanges(content, [
        change({ start_line: 2, end_line: 3, original_text: "    while True:\n" }),
      ]),
    ).toBeNull();
    expect(
      applyProposedChanges(content, [change({ start_line: 40, end_line: 41, original_text: "" })]),
    ).toBeNull();
  });
});

describe("agent API client", () => {
  const diagnostic: Diagnostic = {
    id: "d1",
    severity: "error",
    category: "lint",
    message: "Undefined name `total`",
    file: "a.py",
    line: 3,
    column: 9,
    endLine: 3,
    endColumn: 14,
    source: "ruff",
    code: "F821",
    fixable: false,
    unnecessary: false,
  };

  function capture(status = 200, body: unknown = {}) {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
    );
    return { fetchImpl, client: createApiClient("http://api.test/api/v1", 5000, fetchImpl) };
  }

  it("sends ids and the open file, never the whole project", async () => {
    const { fetchImpl, client } = capture(200, { not: "a run" });
    await expect(
      runAgent(
        {
          projectId: "p1",
          message: "Why?",
          filePath: "a.py",
          code: "x = 1\n",
          selection: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 6 },
          diagnostics: [diagnostic],
        },
        client,
      ),
    ).rejects.toMatchObject({ kind: "malformed" });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/v1/agent/run");
    expect(JSON.parse(String(init.body))).toEqual({
      project_id: "p1",
      message: "Why?",
      file_path: "a.py",
      code: "x = 1\n",
      selection: { start_line: 1, start_column: 1, end_line: 1, end_column: 6 },
      diagnostics: [
        {
          id: "d1",
          severity: "error",
          message: "Undefined name `total`",
          source: "ruff",
          code: "F821",
          category: "lint",
          line: 3,
          column: 9,
          end_line: 3,
          end_column: 14,
        },
      ],
      mode: "assist",
    });
    expect(init.credentials).toBe("include");
  });

  it("omits file content without a file", async () => {
    const { fetchImpl, client } = capture(200, {});
    await runAgent({ projectId: "p1", message: "x", code: "secret" }, client).catch(() => null);
    const body = JSON.parse(
      String((fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body),
    );
    expect(body.code).toBeUndefined();
    expect(body.file_path).toBeUndefined();
  });

  it("surfaces stale and rate-limit errors with their codes", async () => {
    const stale = capture(409, { error: { code: "stale_action", message: "The file changed." } });
    await expect(decideAgentAction("a1", "approve", stale.client)).rejects.toMatchObject({
      status: 409,
      code: "stale_action",
    });
    expect((stale.fetchImpl.mock.calls[0] as unknown as [string])[0]).toBe(
      "http://api.test/api/v1/agent/actions/a1/approve",
    );
    const limited = capture(429, { error: { code: "too_many_agent_runs", message: "Too many." } });
    await expect(runAgent({ projectId: "p1", message: "x" }, limited.client)).rejects.toMatchObject(
      {
        code: "too_many_agent_runs",
      },
    );
  });
});
