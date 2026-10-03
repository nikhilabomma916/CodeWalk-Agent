import { describe, expect, it } from "vitest";

import { DEFAULT_APP_PATH, loginPath, safeNextPath } from "./redirects";
import { normalizeEmail, validateEmail, validateName, validateNewPassword } from "./validation";

describe("password policy (mirrors the backend)", () => {
  it.each([
    ["correct-horse-7", null],
    ["Tr0ub4dor&3", null],
    ["short1!", "Use at least 8 characters."],
    ["onlyletters", "Include at least one number or symbol."],
    ["1234567890", "Include at least one letter."],
    ["        ", "The password cannot be only spaces."],
    ["aaaa1111", "This password is too repetitive."],
    ["x".repeat(129), "Use at most 128 characters."],
  ])("%s", (password, expected) => {
    expect(validateNewPassword(password)).toBe(expected);
  });

  it("rejects the email address as the password", () => {
    expect(validateNewPassword("bob123@example.com", "Bob123@Example.com")).toMatch(/email/);
    expect(validateNewPassword("bob123!x", "bob123!x@example.com")).toMatch(/email/);
  });
});

describe("email and name", () => {
  it("normalizes and validates email", () => {
    expect(normalizeEmail("  Ada@Example.COM ")).toBe("ada@example.com");
    expect(validateEmail("ada@example.com")).toBeNull();
    expect(validateEmail("")).toBe("Enter your email address.");
    expect(validateEmail("ada@")).toBe("Enter a valid email address.");
  });

  it("requires a reasonable name", () => {
    expect(validateName("  ")).toBe("Enter your name.");
    expect(validateName("a".repeat(101))).toMatch(/at most 100/);
    expect(validateName("Ada")).toBeNull();
  });
});

describe("safeNextPath", () => {
  it.each([
    ["/app/history?project=p1", "/app/history?project=p1"],
    ["/app", "/app"],
    ["/app/projects/p1", "/app/projects/p1"],
    [null, DEFAULT_APP_PATH],
    ["https://evil.example/app", DEFAULT_APP_PATH],
    ["//evil.example/app", DEFAULT_APP_PATH],
    ["/application", DEFAULT_APP_PATH],
    ["/login", DEFAULT_APP_PATH],
    ["/app\\..\\evil", DEFAULT_APP_PATH],
  ])("%s -> %s", (next, expected) => {
    expect(safeNextPath(next)).toBe(expected);
  });

  it("builds login links", () => {
    expect(loginPath()).toBe("/login");
    expect(loginPath("/app/history?x=1")).toBe("/login?next=%2Fapp%2Fhistory%3Fx%3D1");
  });
});
