// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, fakeBackend, json, requestsOf, type Route } from "@/testing/fake-api";

import { GitHubImportPanel } from "./github-import-panel";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

const status = (overrides: Record<string, unknown> = {}) => ({
  configured: true,
  connected: true,
  login: "octo-dev",
  scopes: [],
  private_repositories: false,
  connected_at: "2026-10-05T00:00:00Z",
  ...overrides,
});

const REPO = {
  id: 1,
  full_name: "octo/shop",
  owner: "octo",
  name: "shop",
  private: false,
  default_branch: "main",
  description: null,
  size_kb: 12,
  updated_at: null,
};

const RESULT = {
  project_id: "p9",
  project_name: "shop",
  repository: "octo/shop",
  branch: "main",
  commit_sha: "a".repeat(40),
  files_imported: 5,
  files_skipped: 3,
  skipped_by_reason: { secret: 2, binary: 1 },
  skipped: [],
  indexing: "completed",
  indexed_files: 5,
};

function routes(statusBody: unknown, extra: Route[] = []): Route[] {
  return [
    ["GET", /^\/github\/status$/, () => json(statusBody)],
    ["GET", /^\/github\/repositories$/, () => json({ items: [REPO], page: 1, has_more: false })],
    [
      "GET",
      /^\/github\/repositories\/octo\/shop\/branches$/,
      () => json({ items: ["develop", "main"], page: 1, has_more: false }),
    ],
    ...extra,
  ];
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("GitHubImportPanel", () => {
  it("stays hidden when the server has no GitHub integration", async () => {
    const fetchMock = fakeBackend(routes(status({ configured: false, connected: false })));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<GitHubImportPanel callbackResult={null} onImported={vi.fn()} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("stays hidden when the status endpoint fails", async () => {
    const fetchMock = fakeBackend([
      ["GET", /^\/github\/status$/, () => apiError(404, "not_found", "Not found")],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<GitHubImportPanel callbackResult={null} onImported={vi.fn()} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("starts OAuth by sending the browser to GitHub", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const authorize = "https://github.com/login/oauth/authorize?client_id=x&state=s";
    const fetchMock = fakeBackend(
      routes(status({ connected: false, login: null }), [
        ["POST", /^\/github\/connect$/, () => json({ authorize_url: authorize })],
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<GitHubImportPanel callbackResult={null} onImported={vi.fn()} />);
    expect(await screen.findByText(/import public repositories/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect GitHub" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(authorize));
  });

  it("imports the chosen repository branch and reports what was skipped", async () => {
    const onImported = vi.fn();
    const fetchMock = fakeBackend(
      routes(status(), [["POST", /^\/github\/import$/, () => json(RESULT, 201)]]),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<GitHubImportPanel callbackResult="connected" onImported={onImported} />);

    expect(await screen.findByText(/GitHub is connected/)).toBeInTheDocument();
    expect(screen.getByText("@octo-dev")).toBeInTheDocument();
    const repository = await screen.findByLabelText("Repository");
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "octo/shop" })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(repository, "octo/shop");
    await waitFor(() => expect(screen.getByLabelText("Branch")).toHaveValue("main")); // the default branch
    expect(screen.getByLabelText("Project name")).toHaveValue("shop");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText(/Imported 5 files from octo\/shop/)).toBeInTheDocument();
    expect(screen.getByText(/2 credentials files, 1 binary files/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open shop" })).toHaveAttribute(
      "href",
      "/app/uploads/p9",
    );
    expect(onImported).toHaveBeenCalled();
    const sent = requestsOf(fetchMock).find((r) => r.path === "/github/import");
    expect(sent?.body).toEqual({
      owner: "octo",
      repository: "shop",
      branch: "main",
      project_name: "shop",
    });
  });

  it("shows the server's message when an import fails", async () => {
    const fetchMock = fakeBackend(
      routes(status(), [
        [
          "POST",
          /^\/github\/import$/,
          () =>
            apiError(
              413,
              "github_repository_too_large",
              "The repository archive is larger than the import limit.",
            ),
        ],
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<GitHubImportPanel callbackResult={null} onImported={vi.fn()} />);
    const repository = await screen.findByLabelText("Repository");
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "octo/shop" })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(repository, "octo/shop");
    await waitFor(() => expect(screen.getByLabelText("Branch")).toHaveValue("main"));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("larger than the import limit");
  });

  it("shows fixed callback messages only", async () => {
    vi.stubGlobal("fetch", fakeBackend(routes(status({ connected: false, login: null }))));
    const { rerender } = render(
      <GitHubImportPanel callbackResult="github_oauth_state_invalid" onImported={vi.fn()} />,
    );
    expect(await screen.findByText(/authorization expired/)).toBeInTheDocument();
    rerender(<GitHubImportPanel callbackResult="<script>alert(1)</script>" onImported={vi.fn()} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("disconnects", async () => {
    let connected = true;
    const fetchMock = fakeBackend([
      [
        "GET",
        /^\/github\/status$/,
        () => json(status(connected ? {} : { connected: false, login: null })),
      ],
      ["GET", /^\/github\/repositories$/, () => json({ items: [], page: 1, has_more: false })],
      [
        "DELETE",
        /^\/github\/connection$/,
        () => {
          connected = false;
          return new Response(null, { status: 204 });
        },
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<GitHubImportPanel callbackResult={null} onImported={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    expect(await screen.findByRole("button", { name: "Connect GitHub" })).toBeInTheDocument();
    expect(requestsOf(fetchMock).some((r) => r.method === "DELETE")).toBe(true);
  });
});
