import { describe, expect, it } from "vitest";

import type { Diagnostic } from "@/types/diagnostics";

import { toBackendDiagnostic } from "./ai";

const diagnostic: Diagnostic = {
  id: "m1",
  severity: "warning",
  category: "syntax",
  message: "Unexpected token",
  file: "a.ts",
  line: 4,
  column: 7,
  endLine: 4,
  endColumn: 3,
  source: "typescript",
  fixable: false,
  unnecessary: false,
};

describe("toBackendDiagnostic", () => {
  it("maps to the backend shape and repairs inverted single-line ranges", () => {
    expect(toBackendDiagnostic(diagnostic)).toEqual({
      id: "m1",
      severity: "warning",
      message: "Unexpected token",
      source: "typescript",
      code: null,
      category: "syntax",
      line: 4,
      column: 7,
      end_line: 4,
      end_column: 7,
    });
  });

  it("keeps multi-line ranges and bounds long text", () => {
    const mapped = toBackendDiagnostic({
      ...diagnostic,
      endLine: 6,
      endColumn: 2,
      message: "x".repeat(5000),
      code: "TS1005",
    });
    expect([mapped.end_line, mapped.end_column, mapped.code]).toEqual([6, 2, "TS1005"]);
    expect(mapped.message).toHaveLength(2000);
  });
});
