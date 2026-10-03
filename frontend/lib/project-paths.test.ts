import { describe, expect, it } from "vitest";

import {
  ancestorPaths,
  buildTree,
  isIgnoredPath,
  isSecretFile,
  validateNewFilePath,
} from "./project-paths";

describe("buildTree", () => {
  it("nests entries, implies missing folders, and sorts folders first", () => {
    const tree = buildTree(
      [
        { path: "src/utils/b.ts", type: "file" },
        { path: "README.md", type: "file" },
        { path: "src/a.py", type: "file" },
        { path: "docs", type: "folder" },
      ],
      "demo",
    );

    expect(tree.name).toBe("demo");
    expect(tree.children.map((node) => node.name)).toEqual(["docs", "src", "README.md"]);
    const src = tree.children[1];
    expect(src.type).toBe("folder");
    if (src.type !== "folder") return;
    expect(src.children.map((node) => node.path)).toEqual(["src/utils", "src/a.py"]);
    const file = src.children[1];
    expect(file.type === "file" && file.language).toBe("python");
  });
});

describe("ignore rules", () => {
  it("skips dependency folders and secret files", () => {
    expect(isIgnoredPath("node_modules/react/index.js")).toBe(true);
    expect(isIgnoredPath("backend/.venv/lib/site.py")).toBe(true);
    expect(isIgnoredPath("app/__pycache__/x.pyc")).toBe(true);
    expect(isIgnoredPath(".env")).toBe(true);
    expect(isIgnoredPath("config/.env.local")).toBe(true);
    expect(isIgnoredPath("src/main.py")).toBe(false);
    expect(isSecretFile(".env.example")).toBe(false);
  });
});

describe("validateNewFilePath", () => {
  it("accepts nested relative paths", () => {
    expect(validateNewFilePath("src/utils/math.ts")).toBeNull();
  });

  it.each([
    "",
    "   ",
    "/abs.ts",
    "C:/x.ts",
    "../up.ts",
    "a//b.ts",
    "a/./b.ts",
    "bad:name.ts",
    ".env",
  ])("rejects %j", (value) => {
    expect(validateNewFilePath(value)).not.toBeNull();
  });
});

describe("ancestorPaths", () => {
  it("lists parent folders outermost first", () => {
    expect(ancestorPaths("a/b/c.ts")).toEqual(["a", "a/b"]);
    expect(ancestorPaths("root.ts")).toEqual([]);
  });
});
