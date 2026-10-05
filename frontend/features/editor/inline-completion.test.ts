import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api/errors";

import {
  completionModeAt,
  InlineCompletionEngine,
  isActionableComment,
  type CompletionInput,
} from "./inline-completion";
import {
  createInlineCompletionsProvider,
  inlineCompletionConfig,
} from "./inline-completion-provider";
import type { Monaco } from "./monaco-setup";

const INPUT: CompletionInput = {
  filePath: "app/main.py",
  language: "python",
  prefix: "def calculate_total(price, quantity):\n    return ",
  suffix: "",
  mode: "auto",
};

afterEach(() => {
  vi.useRealTimers();
  inlineCompletionConfig.enabled = false;
});

describe("when to ask", () => {
  it.each([
    ["# create a function to calculate student average", true],
    ["// connect to MySQL database", true],
    ["  # TODO: add validation for the email field", true],
    ["/* create API endpoint for student registration */", true],
    ["# TODO", false],
    ["# version 2", false],
    ["x = 1  # create a list", false],
    ["# add", false],
  ])("%s → actionable %s", (line, expected) => {
    expect(isActionableComment(line)).toBe(expected);
  });

  it("asks at the end of the text of a line, not in the middle of a word", () => {
    expect(completionModeAt("x = calc", "")).toBe("auto");
    expect(completionModeAt("print(calc", ")")).toBe("auto"); // only a closing bracket follows
    expect(completionModeAt("x = calc", "ulate()")).toBeNull();
  });

  it("asks on an empty line only at the start of a block or after an actionable comment", () => {
    expect(completionModeAt("def f(a, b):\n    ", "")).toBe("auto");
    expect(completionModeAt("function f() {\n  ", "")).toBe("auto");
    expect(completionModeAt("x = 1\n", "")).toBeNull();
    expect(completionModeAt("# create a function to calculate student average\n", "")).toBe(
      "comment",
    );
  });

  it("does not complete inside comments unless asked explicitly", () => {
    expect(completionModeAt("# this function", "")).toBeNull();
    expect(completionModeAt("x = 1\n", "", true)).toBe("auto");
  });
});

describe("InlineCompletionEngine", () => {
  it("waits for typing to pause and is cancelled by the next keystroke", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => "price * quantity");
    const engine = new InlineCompletionEngine(fetcher, { debounceMs: 400 });
    const first = new AbortController();
    const pending = engine.complete(INPUT, { signal: first.signal });
    await vi.advanceTimersByTimeAsync(200);
    first.abort(); // the developer typed again
    expect(await pending).toBeNull();
    const second = engine.complete(
      { ...INPUT, prefix: INPUT.prefix + "p" },
      {
        signal: new AbortController().signal,
      },
    );
    await vi.advanceTimersByTimeAsync(400);
    expect(await second).toBe("price * quantity");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("never asks twice for the same context", async () => {
    const fetcher = vi.fn(async () => "price * quantity");
    const engine = new InlineCompletionEngine(fetcher, { debounceMs: 0 });
    const signal = new AbortController().signal;
    const [a, b] = await Promise.all([
      engine.complete(INPUT, { signal }),
      engine.complete(INPUT, { signal }),
    ]);
    expect([a, b]).toEqual(["price * quantity", "price * quantity"]);
    expect(await engine.complete(INPUT, { signal })).toBe("price * quantity"); // cached
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("pauses automatic requests after the provider refuses (quota), but not explicit ones", async () => {
    let now = 1_000;
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError("http", "No credit.", { status: 502, code: "ai_quota_exceeded" }),
      )
      .mockResolvedValue("price * quantity");
    const statuses: string[] = [];
    const engine = new InlineCompletionEngine(fetcher, {
      debounceMs: 0,
      backoffMs: 60_000,
      now: () => now,
      onStatus: (s) => statuses.push(s.state),
    });
    const signal = new AbortController().signal;
    expect(await engine.complete(INPUT, { signal })).toBeNull();
    expect(engine.status).toMatchObject({ state: "paused", code: "ai_quota_exceeded" });
    now += 30_000;
    expect(await engine.complete({ ...INPUT, prefix: "a" }, { signal })).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1); // nothing sent while paused
    expect(await engine.complete({ ...INPUT, prefix: "b" }, { signal, explicit: true })).toBe(
      "price * quantity",
    );
    now += 60_000;
    expect(await engine.complete({ ...INPUT, prefix: "c" }, { signal })).toBe("price * quantity");
    expect(statuses).toContain("paused");
  });

  it("does not pause on transient failures", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("network", "offline"))
      .mockResolvedValue("x");
    const engine = new InlineCompletionEngine(fetcher, { debounceMs: 0 });
    const signal = new AbortController().signal;
    expect(await engine.complete(INPUT, { signal })).toBeNull();
    expect(engine.status.state).toBe("idle");
    expect(await engine.complete({ ...INPUT, prefix: "y" }, { signal })).toBe("x");
  });
});

describe("Monaco provider", () => {
  /** A minimal Monaco model over `lines`, with the cursor at `line`/`column`. */
  function fakeModel(lines: string[], version = { id: 1 }) {
    const text = (sl: number, sc: number, el: number, ec: number) => {
      const out: string[] = [];
      for (let l = sl; l <= el; l++) {
        const content = lines[l - 1];
        out.push(content.slice(l === sl ? sc - 1 : 0, l === el ? ec - 1 : content.length));
      }
      return out.join("\n");
    };
    return {
      uri: { toString: () => "file:///p1/app/main.py" },
      getLineContent: (n: number) => lines[n - 1],
      getLineCount: () => lines.length,
      getLineMaxColumn: (n: number) => lines[n - 1].length + 1,
      getLanguageId: () => "python",
      getVersionId: () => version.id,
      getValueInRange: (r: {
        startLineNumber: number;
        startColumn: number;
        endLineNumber: number;
        endColumn: number;
      }) => text(r.startLineNumber, r.startColumn, r.endLineNumber, r.endColumn),
    };
  }
  const monaco = {
    languages: { InlineCompletionTriggerKind: { Automatic: 0, Explicit: 1 } },
    Range: class {
      constructor(
        public startLineNumber: number,
        public startColumn: number,
        public endLineNumber: number,
        public endColumn: number,
      ) {}
    },
  } as unknown as Monaco;
  const token = () => ({
    isCancellationRequested: false,
    onCancellationRequested: () => ({ dispose() {} }),
  });
  const context = { triggerKind: 0 } as never;

  it("offers the completion as ghost text at the cursor", async () => {
    inlineCompletionConfig.enabled = true;
    inlineCompletionConfig.pathFor = () => "app/main.py";
    const engine = { complete: vi.fn(async (_input: CompletionInput) => "price * quantity") };
    const provider = createInlineCompletionsProvider(monaco, engine);
    const model = fakeModel(["def calculate_total(price, quantity):", "    return "]);
    const result = await provider.provideInlineCompletions(
      model as never,
      { lineNumber: 2, column: 12 } as never,
      context,
      token() as never,
    );
    expect(result?.items[0]).toMatchObject({
      insertText: "price * quantity",
      range: { startLineNumber: 2, startColumn: 12, endLineNumber: 2, endColumn: 12 },
    });
    expect(engine.complete.mock.calls[0][0]).toMatchObject({
      filePath: "app/main.py",
      prefix: "def calculate_total(price, quantity):\n    return ",
      mode: "auto",
    });
  });

  it("drops a stale answer and does nothing when disabled", async () => {
    inlineCompletionConfig.enabled = true;
    inlineCompletionConfig.pathFor = () => "app/main.py";
    const version = { id: 1 };
    const engine = {
      complete: vi.fn(async () => {
        version.id = 2; // the developer kept typing
        return "price";
      }),
    };
    const provider = createInlineCompletionsProvider(monaco, engine);
    const model = fakeModel(["x = "], version);
    const stale = await provider.provideInlineCompletions(
      model as never,
      { lineNumber: 1, column: 5 } as never,
      context,
      token() as never,
    );
    expect(stale?.items).toEqual([]);
    inlineCompletionConfig.enabled = false;
    const off = await provider.provideInlineCompletions(
      model as never,
      { lineNumber: 1, column: 5 } as never,
      context,
      token() as never,
    );
    expect(off?.items).toEqual([]);
    expect(engine.complete).toHaveBeenCalledTimes(1);
  });

  it("keeps only the first line when text follows the cursor", async () => {
    inlineCompletionConfig.enabled = true;
    inlineCompletionConfig.pathFor = () => "app/main.py";
    const engine = { complete: vi.fn(async () => "a, b\nprint(a)") };
    const provider = createInlineCompletionsProvider(monaco, engine);
    const model = fakeModel(["call()"]);
    const result = await provider.provideInlineCompletions(
      model as never,
      { lineNumber: 1, column: 6 } as never,
      context,
      token() as never,
    );
    expect(result?.items[0].insertText).toBe("a, b");
  });
});
