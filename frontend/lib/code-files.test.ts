import { describe, expect, it } from "vitest";

import { UNSUPPORTED_FILE_TYPE, validateCodeFileName } from "./code-files";

describe("validateCodeFileName", () => {
  it.each([
    "main.py",
    "hello.java",
    "app.js",
    "index.ts",
    "program.cpp",
    "index.html",
    "README.md",
    " test.py ",
  ])("accepts %j", (name) => {
    expect(validateCodeFileName(name)).toBeNull();
  });

  it.each(["setup.exe", "lib.dll", "clip.mp4", "a.zip", "logo.png", "photo.JPG", "notes", ".py"])(
    "rejects the non-code file %j",
    (name) => {
      expect(validateCodeFileName(name)).toBe(UNSUPPORTED_FILE_TYPE);
    },
  );

  it.each([
    ["", "Enter a file name"],
    ["../../evil.py", "without folders"],
    ["C:\\Windows\\file.py", "without folders"],
    ["/etc/passwd", "without folders"],
    ["src/main.py", "without folders"],
    [".", "not allowed"],
    ["..", "not allowed"],
    ["bad\u0000name.py", "not allowed"],
    ["tab\tname.py", "not allowed"],
    ["what?.py", "cannot contain"],
    ["a".repeat(253) + ".py", "at most 255"],
    [".env", "Credentials"],
  ])("rejects %j", (name, message) => {
    expect(validateCodeFileName(name)).toContain(message);
  });
});
