import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AnalysisOutcome } from "@/services/api/analysis";

import { analysisLanguageFor } from "./analysis-language";
import { LiveAnalysisScheduler, type AnalyzeFn, type LiveAnalysisCallbacks } from "./live-analysis";

function outcome(label: string): AnalysisOutcome {
  return {
    language: "python",
    success: true,
    diagnostics: [
      {
        id: label,
        severity: "error",
        category: "syntax",
        message: label,
        file: "a.py",
        line: 1,
        column: 1,
        endLine: 1,
        endColumn: 2,
        source: "python",
        fixable: false,
        unnecessary: false,
      },
    ],
    capabilities: [],
    errors: [],
    durationMs: 1,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function callbacks(): LiveAnalysisCallbacks & { results: string[]; errors: unknown[] } {
  const results: string[] = [];
  const errors: unknown[] = [];
  return {
    results,
    errors,
    onPending: vi.fn(),
    onStart: vi.fn(),
    onResult: (_path, value) => results.push(value.diagnostics[0].message),
    onError: (_path, error) => errors.push(error),
  };
}

describe("LiveAnalysisScheduler", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces rapid edits into a single request for the newest content", async () => {
    const analyze = vi.fn<AnalyzeFn>(async (request) => outcome(request.content));
    const cb = callbacks();
    const scheduler = new LiveAnalysisScheduler(analyze, cb, 400);

    scheduler.schedule({ path: "a.py", content: "v1" });
    await vi.advanceTimersByTimeAsync(200);
    scheduler.schedule({ path: "a.py", content: "v2" });
    await vi.advanceTimersByTimeAsync(200);
    scheduler.schedule({ path: "a.py", content: "v3" });
    await vi.advanceTimersByTimeAsync(399);
    expect(analyze).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(analyze).toHaveBeenCalledTimes(1);
    expect(analyze.mock.calls[0][0].content).toBe("v3");
    expect(cb.results).toEqual(["v3"]);
  });

  it("never applies a late response for older content over a newer result", async () => {
    const first = deferred<AnalysisOutcome>();
    const second = deferred<AnalysisOutcome>();
    const signals: AbortSignal[] = [];
    // An analyzer that ignores abort, to prove the sequence guard alone is enough.
    const analyze = vi
      .fn<AnalyzeFn>()
      .mockImplementationOnce((_request, signal) => {
        signals.push(signal);
        return first.promise;
      })
      .mockImplementationOnce((_request, signal) => {
        signals.push(signal);
        return second.promise;
      });
    const cb = callbacks();
    const scheduler = new LiveAnalysisScheduler(analyze, cb, 100);

    scheduler.schedule({ path: "a.py", content: "old" });
    await vi.advanceTimersByTimeAsync(100); // request 1 in flight
    scheduler.schedule({ path: "a.py", content: "new" });
    expect(signals[0].aborted).toBe(true); // an edit aborts the stale request immediately
    await vi.advanceTimersByTimeAsync(100); // request 2 in flight

    second.resolve(outcome("new"));
    await vi.runAllTimersAsync();
    first.resolve(outcome("old")); // arrives last
    await vi.runAllTimersAsync();

    expect(cb.results).toEqual(["new"]);
  });

  it("reports errors only for the current request", async () => {
    const analyze = vi
      .fn<AnalyzeFn>()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(outcome("ok"));
    const cb = callbacks();
    const scheduler = new LiveAnalysisScheduler(analyze, cb, 50);

    scheduler.schedule({ path: "a.py", content: "x" });
    await vi.advanceTimersByTimeAsync(50);
    expect(cb.errors).toHaveLength(1);

    scheduler.schedule({ path: "a.py", content: "y" });
    await vi.advanceTimersByTimeAsync(50);
    expect(cb.results).toEqual(["ok"]);
  });

  it("cancel drops pending work", async () => {
    const analyze = vi.fn<AnalyzeFn>(async () => outcome("x"));
    const scheduler = new LiveAnalysisScheduler(analyze, callbacks(), 50);
    scheduler.schedule({ path: "a.py", content: "x" });
    scheduler.cancel();
    await vi.advanceTimersByTimeAsync(100);
    expect(analyze).not.toHaveBeenCalled();
  });
});

describe("analysisLanguageFor", () => {
  it("lets the backend detect the language unless overridden", () => {
    expect(analysisLanguageFor("a.py")).toBeUndefined();
  });

  it("maps editor overrides to backend languages", () => {
    expect(analysisLanguageFor("App.tsx", "typescript")).toBe("typescriptreact");
    expect(analysisLanguageFor("a.ts", "typescript")).toBe("typescript");
    expect(analysisLanguageFor("a.jsx", "javascript")).toBe("javascriptreact");
    expect(analysisLanguageFor("notes.txt", "python")).toBe("python");
    // Editor-only languages must not fall back to extension detection.
    expect(analysisLanguageFor("script.py", "powershell")).toBe("plaintext");
  });
});
