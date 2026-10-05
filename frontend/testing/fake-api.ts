/**
 * Test helpers: a fetch stub that answers like the backend for the routes a
 * test declares (anything else is a 404 in the backend's error format), plus
 * fixtures shaped exactly like the backend schemas.
 */
import { vi } from "vitest";

import type { User } from "@/services/api/auth";
import type { HistoryEvent } from "@/services/api/history";
import type { ServerProject } from "@/services/api/projects";

export type Route = [
  method: string,
  path: RegExp,
  respond: (url: URL, body: unknown) => Response | Promise<Response>,
];

export function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(status: number, code: string, message: string): Response {
  return json({ error: { code, message } }, status);
}

export function page<T>(items: T[]) {
  return { items, total: items.length, limit: 50, offset: 0 };
}

export function fakeBackend(routes: Route[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    for (const [routeMethod, pattern, respond] of routes) {
      if (routeMethod === method && pattern.test(path)) return respond(url, body);
    }
    return apiError(404, "not_found", "Not found");
  });
}

/** The (method, path, body) of every request made through a fakeBackend stub. */
export function requestsOf(fetchMock: ReturnType<typeof fakeBackend>) {
  return fetchMock.mock.calls.map(([input, init]) => ({
    method: init?.method ?? "GET",
    path: new URL(String(input)).pathname.replace(/^\/api\/v1/, ""),
    search: new URL(String(input)).search,
    body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    credentials: init?.credentials,
  }));
}

export const testUser: User = {
  id: "u1",
  name: "Ada Lovelace",
  email: "ada@example.com",
  created_at: "2026-09-01T10:00:00Z",
  last_login_at: "2026-10-01T09:00:00Z",
};

export function makeProject(overrides: Partial<ServerProject> = {}): ServerProject {
  return {
    id: "p1",
    name: "Payments service",
    description: "Billing and invoices",
    root_path: null,
    read_only: false,
    origin: "workspace",
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-10-01T08:00:00Z",
    stats: {
      file_count: 2,
      total_bytes: 64,
      total_lines: 5,
      languages: [{ language: "python", files: 2 }],
      last_analyzed_at: null,
    },
    ...overrides,
  };
}

export function makeEvent(overrides: Partial<HistoryEvent> = {}): HistoryEvent {
  return {
    id: "e1",
    event_type: "file.updated",
    project_id: "p1",
    project_name: "Payments service",
    file_id: "f1",
    file_path: "src/app.py",
    analysis_id: "a1",
    details: { version: 2, diagnostic_count: 1, analysis_status: "completed" },
    created_at: new Date().toISOString(),
    ...overrides,
  };
}
