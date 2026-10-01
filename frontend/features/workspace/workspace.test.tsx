// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Workspace } from "./workspace";

const healthyBody = {
  status: "ok",
  service: "CodeWalk Agent API",
  version: "0.1.0",
  environment: "development",
  timestamp: "2026-09-30T00:00:00Z",
  uptime_seconds: 12,
  checks: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("Workspace backend status", () => {
  it("shows online only after a real successful health response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(healthyBody), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Workspace />);

    expect(screen.getByText("Backend: checking…")).toBeInTheDocument();
    expect(await screen.findByText("Backend: online")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/health",
      expect.anything(),
    );
  });

  it("shows offline when the backend cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    render(<Workspace />);

    expect(await screen.findByText("Backend: offline")).toBeInTheDocument();
    expect(screen.queryByText("Backend: online")).not.toBeInTheDocument();
  });

  it("shows an error when the backend answers with an unexpected payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ hello: "world" }), { status: 200 })),
    );

    render(<Workspace />);

    expect(await screen.findByText("Backend: error")).toBeInTheDocument();
  });

  it("offers project actions when no project is open", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<Workspace />);
    expect(screen.getAllByRole("button", { name: "New project" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Open folder" }).length).toBeGreaterThan(0);
  });
});

describe("Workspace server projects", () => {
  function routedFetch(databaseStatus: "pass" | "not_configured") {
    return vi.fn(async (url: string) => {
      if (url.endsWith("/health")) {
        return new Response(
          JSON.stringify({
            ...healthyBody,
            checks: [
              {
                name: "database",
                status: databaseStatus,
                required: false,
                latency_ms: 1,
                detail: null,
              },
            ],
          }),
        );
      }
      if (url.includes("/projects/workspace")) {
        return new Response(JSON.stringify({ enabled: false, folders: [] }));
      }
      if (url.includes("/projects?")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                id: "p1",
                name: "Payments service",
                description: null,
                root_path: null,
                read_only: false,
                created_at: "2026-10-01T00:00:00Z",
                updated_at: "2026-10-01T00:00:00Z",
              },
            ],
            total: 1,
            limit: 200,
            offset: 0,
          }),
        );
      }
      return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found" } }), {
        status: 404,
      });
    });
  }

  it("lists stored projects when the database is connected", async () => {
    vi.stubGlobal("fetch", routedFetch("pass"));
    render(<Workspace />);
    expect(await screen.findByText("Payments service")).toBeInTheDocument();
    expect(await screen.findByText("Database: connected")).toBeInTheDocument();
  });

  it("explains why server projects are unavailable without a database", async () => {
    vi.stubGlobal("fetch", routedFetch("not_configured"));
    render(<Workspace />);
    expect(
      await screen.findByText(
        /Server projects are unavailable: The server has no database configured/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Database: not configured")).toBeInTheDocument();
  });
});
