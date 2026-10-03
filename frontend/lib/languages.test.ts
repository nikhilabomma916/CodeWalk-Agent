import { describe, expect, it } from "vitest";

import { detectLanguage, isLanguageId, languageLabel } from "./languages";

describe("detectLanguage", () => {
  it.each([
    ["main.py", "python"],
    ["src/app.ts", "typescript"],
    ["src/App.tsx", "typescript"],
    ["index.js", "javascript"],
    ["component.jsx", "javascript"],
    ["package.json", "json"],
    ["index.html", "html"],
    ["styles/site.css", "css"],
    ["Main.java", "java"],
    ["lib.c", "c"],
    ["lib.hpp", "cpp"],
    ["query.sql", "sql"],
    ["README.md", "markdown"],
    ["config.yaml", "yaml"],
    ["pyproject.toml", "ini"],
    ["Dockerfile", "dockerfile"],
    ["docker/Dockerfile.dev", "dockerfile"],
    ["UPPER.PY", "python"],
  ])("%s -> %s", (filename, expected) => {
    expect(detectLanguage(filename)).toBe(expected);
  });

  it("falls back to plaintext for unknown or missing extensions", () => {
    expect(detectLanguage("LICENSE")).toBe("plaintext");
    expect(detectLanguage("archive.xyz")).toBe("plaintext");
    expect(detectLanguage(".hidden")).toBe("plaintext");
    expect(detectLanguage("trailing.")).toBe("plaintext");
  });
});

describe("language registry", () => {
  it("recognizes known ids and labels them", () => {
    expect(isLanguageId("python")).toBe(true);
    expect(isLanguageId("klingon")).toBe(false);
    expect(languageLabel("cpp")).toBe("C++");
  });
});
