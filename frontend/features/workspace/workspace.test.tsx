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
