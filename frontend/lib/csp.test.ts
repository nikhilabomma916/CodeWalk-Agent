import { describe, expect, it } from "vitest";

import { parseApiBaseUrl } from "./config";
import { apiOrigin, buildContentSecurityPolicy } from "./csp";

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

const base = { nonce: "bm9uY2U=", development: false, apiBaseUrl: "/api/v1", https: true };

describe("buildContentSecurityPolicy", () => {
  it("allows only nonce-bearing scripts in production: no inline, eval, or wildcard", () => {
    const script = directives(buildContentSecurityPolicy(base)).get("script-src") ?? [];
    expect(script).toEqual(["'self'", "'nonce-bm9uY2U='", "'strict-dynamic'"]);
    expect(script.join(" ")).not.toMatch(/unsafe-inline|unsafe-eval|\*|https?:/);
  });

  it("adds eval only in development", () => {
    const dev = directives(buildContentSecurityPolicy({ ...base, development: true }));
    expect(dev.get("script-src")).toContain("'unsafe-eval'");
  });

  it("locks down framing, plugins, base URLs and form targets", () => {
    const policy = directives(buildContentSecurityPolicy(base));
    expect(policy.get("default-src")).toEqual(["'self'"]);
    expect(policy.get("object-src")).toEqual(["'none'"]);
    expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    expect(policy.get("base-uri")).toEqual(["'self'"]);
    expect(policy.get("form-action")).toEqual(["'self'"]);
  });

  it("allows the editor's workers and styles, and nothing remote", () => {
    const policy = directives(buildContentSecurityPolicy(base));
    expect(policy.get("worker-src")).toEqual(["'self'", "blob:"]);
    expect(policy.get("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
    for (const values of policy.values()) {
      expect(values.join(" ")).not.toMatch(/(^|\s)\*(\s|$)|https?:\/\//);
    }
  });

  it("connects only to its own origin behind the proxy, and to the API origin otherwise", () => {
    expect(directives(buildContentSecurityPolicy(base)).get("connect-src")).toEqual(["'self'"]);
    const crossOrigin = buildContentSecurityPolicy({
      ...base,
      apiBaseUrl: "http://localhost:8000/api/v1",
    });
    expect(directives(crossOrigin).get("connect-src")).toEqual(["'self'", "http://localhost:8000"]);
  });

  it("upgrades insecure requests only on HTTPS pages", () => {
    expect(buildContentSecurityPolicy(base)).toContain("upgrade-insecure-requests");
    expect(buildContentSecurityPolicy({ ...base, https: false })).not.toContain(
      "upgrade-insecure-requests",
    );
  });
});

describe("apiOrigin", () => {
  it("is null for same-origin paths", () => {
    expect(apiOrigin("/api/v1")).toBeNull();
    expect(apiOrigin("https://codewalk.example.com/api/v1")).toBe("https://codewalk.example.com");
  });
});

describe("parseApiBaseUrl", () => {
  it("accepts absolute http(s) URLs and same-origin paths", () => {
    expect(parseApiBaseUrl("http://localhost:8000/api/v1/")).toBe("http://localhost:8000/api/v1");
    expect(parseApiBaseUrl("/api/v1/")).toBe("/api/v1");
    expect(parseApiBaseUrl(undefined)).toBe("http://localhost:8000/api/v1");
  });

  it("rejects protocol-relative, other-scheme and malformed values", () => {
    for (const value of [
      "//evil.example/api",
      "javascript:alert(1)",
      "ftp://x/api",
      "api/v1",
      "/a b",
    ]) {
      expect(() => parseApiBaseUrl(value)).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
    }
  });
});
