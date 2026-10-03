// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Diagnostic } from "@/types/diagnostics";

import { ProblemsList } from "./problems-list";
import { describeAnalysis } from "./problems-panel";

const diagnostics: Diagnostic[] = [
  {
    id: "d1",
    severity: "error",
    category: "syntax",
    message: "invalid syntax",
    file: "src/app.py",
    line: 3,
    column: 7,
    endLine: 3,
    endColumn: 8,
    source: "python",
    code: "SyntaxError",
    fixable: false,
    unnecessary: false,
  },
  {
    id: "d2",
    severity: "warning",
    category: "lint",
    message: "`os` imported but unused",
    file: "src/app.py",
    line: 1,
    column: 8,
    endLine: 1,
    endColumn: 10,
    source: "ruff",
    code: "F401",
    suggestedAction: "Remove unused import: `os`",
    fixable: true,
    unnecessary: false,
  },
];

describe("ProblemsList", () => {
  it("renders severity, message, source, code, and location", () => {
    render(<ProblemsList diagnostics={diagnostics} onSelect={vi.fn()} />);
    expect(screen.getByText("invalid syntax")).toBeInTheDocument();
    expect(screen.getByText("python(SyntaxError)")).toBeInTheDocument();
    expect(screen.getByText("src/app.py:3:7")).toBeInTheDocument();
    expect(screen.getByText("Fix: Remove unused import: `os`")).toBeInTheDocument();
  });

  it("navigates to the clicked problem", async () => {
    const onSelect = vi.fn();
    render(<ProblemsList diagnostics={diagnostics} onSelect={onSelect} />);
    await userEvent.click(
      screen.getByRole("button", { name: /Error: invalid syntax at src\/app.py line 3, column 7/ }),
    );
    expect(onSelect).toHaveBeenCalledWith(diagnostics[0]);
  });

  it("updates when diagnostics change", () => {
    const { rerender } = render(<ProblemsList diagnostics={diagnostics} onSelect={vi.fn()} />);
    rerender(<ProblemsList diagnostics={[diagnostics[1]]} onSelect={vi.fn()} />);
    expect(screen.queryByText("invalid syntax")).not.toBeInTheDocument();
    expect(screen.getByText("`os` imported but unused")).toBeInTheDocument();
  });
});

describe("describeAnalysis", () => {
  it("states exactly what ran", () => {
    expect(
      describeAnalysis({
        status: "done",
        language: "python",
        success: true,
        capabilities: [
          { kind: "syntax", status: "performed", analyzer: "python-ast", detail: null },
          { kind: "types", status: "not_supported", analyzer: null, detail: null },
        ],
        errors: [],
        durationMs: 12.4,
      }),
    ).toBe("python: syntax ✓ · types — (12 ms)");
  });

  it("reports unsupported languages and backend outages honestly", () => {
    expect(
      describeAnalysis({
        status: "done",
        language: "yaml",
        success: true,
        capabilities: [{ kind: "syntax", status: "not_supported", analyzer: null, detail: null }],
        errors: [],
        durationMs: 0,
      }),
    ).toBe("No analyzer is available for yaml.");
    expect(
      describeAnalysis({ status: "unavailable", message: "Unable to reach the CodeWalk backend" }),
    ).toBe("Analysis unavailable: Unable to reach the CodeWalk backend");
  });
});
