import { afterEach, describe, expect, it, vi } from "vitest";

import { databaseStatus } from "@/features/status-bar/status-bar";
import type { HealthResponse } from "@/services/api/health";

import { serverAvailability } from "../use-server-projects";

import { ServerProjectSource } from "./server-source";

const project = {
  id: "p1",
  name: "Demo",
  description: null,
  root_path: null,
  read_only: false,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

function file(id: string, path: string) {
  return {
    id,
    project_id: "p1",
    path,
    name: path.split("/").pop(),
    language: "python",
    size: 3,
    line_count: 1,
    content_hash: "h",
    has_content: true,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => vi.unstubAllGlobals());

describe("ServerProjectSource", () => {
  it("lists files with implied folders and reads/writes by file id", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url.replace("http://localhost:8000/api/v1", "")}`);
        if (url.includes("/files?")) {
          return json({ items: [file("f1", "src/a.py")], total: 1, limit: 5000, offset: 0 });
        }
        if (init?.method === "PATCH")
          return json({ file: { ...file("f1", "src/a.py"), content: "x" }, analysis: null });
        return json({ ...file("f1", "src/a.py"), content: "print(1)\n" });
      }),
    );
    const source = new ServerProjectSource(project);
    const listing = await source.list();
    expect(listing.entries).toEqual([
      { path: "src", type: "folder" },
      { path: "src/a.py", type: "file", size: 3 },
    ]);
    expect(await source.read("src/a.py")).toBe("print(1)\n");
    await source.write("src/a.py", "x");
    expect(calls).toEqual([
      "GET /projects/p1/files?limit=5000&offset=0",
      "GET /projects/p1/files/f1",
      "PATCH /projects/p1/files/f1",
    ]);
  });

  it("rejects writes to read-only (linked) projects without calling the server", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const source = new ServerProjectSource({ ...project, root_path: "service", read_only: true });
    await expect(source.write("a.py", "x")).rejects.toMatchObject({ reason: "read-only" });
    await expect(source.createFile("b.py")).rejects.toMatchObject({ reason: "read-only" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps server conflicts to source errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ error: { code: "file_exists", message: "a.py already exists." } }, 409),
      ),
    );
    await expect(new ServerProjectSource(project).createFile("a.py")).rejects.toMatchObject({
      reason: "exists",
    });
  });
});

function health(databaseCheck: HealthResponse["checks"][number]["status"]): HealthResponse {
  return {
    status: databaseCheck === "fail" ? "degraded" : "ok",
    service: "CodeWalk Agent API",
    version: "0.1.0",
    environment: "development",
    timestamp: "2026-10-01T00:00:00Z",
    uptime_seconds: 1,
    checks: [
      { name: "database", status: databaseCheck, required: false, latency_ms: 1, detail: null },
    ],
  };
}

describe("server availability", () => {
  const checkedAt = new Date();

  it("is available only when the real health check says the database is connected", () => {
    expect(
      serverAvailability({ state: "online", health: health("pass"), latencyMs: 1, checkedAt }),
    ).toEqual({
      available: true,
    });
    expect(
      serverAvailability({
        state: "online",
        health: health("not_configured"),
        latencyMs: 1,
        checkedAt,
      }),
    ).toMatchObject({
      available: false,
    });
    expect(
      serverAvailability({ state: "degraded", health: health("fail"), latencyMs: 1, checkedAt }),
    ).toMatchObject({
      available: false,
      reason: "The server's database is unavailable.",
    });
    expect(serverAvailability({ state: "offline", message: "down", checkedAt })).toMatchObject({
      available: false,
    });
  });

  it("never claims a database state when the backend is unreachable", () => {
    expect(databaseStatus({ state: "offline", message: "down", checkedAt })).toBeNull();
    expect(
      databaseStatus({ state: "online", health: health("pass"), latencyMs: 1, checkedAt })?.label,
    ).toBe("Database: connected");
  });
});
