// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import {
  apiError,
  fakeBackend,
  json,
  makeProject,
  page,
  requestsOf,
  type Route,
} from "@/testing/fake-api";
import { navigation } from "@/testing/next-navigation";

import { ProjectDetailPage } from "./project-detail-page";
import { ProjectsPage } from "./projects-page";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

const workspaceDisabled: Route = [
  "GET",
  /^\/projects\/workspace$/,
  () => json({ enabled: false, folders: [] }),
];

beforeAll(() => {
  // jsdom has no <dialog> support.
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
beforeEach(() => navigation.reset("/app/projects"));
afterEach(() => vi.unstubAllGlobals());

function renderPage(ui: ReactElement, routes: Route[]) {
  const fetchMock = fakeBackend(routes);
  vi.stubGlobal("fetch", fetchMock);
  render(<WorkspaceProviders>{ui}</WorkspaceProviders>);
  return fetchMock;
}

describe("ProjectsPage", () => {
  it("lists the user's projects as returned by the backend", async () => {
    renderPage(<ProjectsPage />, [
      workspaceDisabled,
      [
        "GET",
        /^\/projects$/,
        () =>
          json(
            page([
              makeProject(),
              makeProject({
                id: "p2",
                name: "Docs site",
                description: null,
                stats: {
                  file_count: 0,
                  total_bytes: 0,
                  total_lines: 0,
                  languages: [],
                  last_analyzed_at: null,
                },
              }),
            ]),
          ),
      ],
    ]);
    const first = (await screen.findByText("Payments service")).closest("a")!;
    expect(first).toHaveAttribute("href", "/app/projects/p1");
    expect(within(first).getByText("Billing and invoices")).toBeInTheDocument();
    expect(within(first).getByText("2 files · 5 lines")).toBeInTheDocument();
    expect(within(first).getByText("Python")).toBeInTheDocument();
    expect(within(first).getByText("Not analyzed")).toBeInTheDocument();
    const second = screen.getByText("Docs site").closest("a")!;
    expect(within(second).getByText("No description")).toBeInTheDocument();
    expect(screen.getByText("2 projects")).toBeInTheDocument();
  });

  it("shows an empty state that creates a project", async () => {
    renderPage(<ProjectsPage />, [
      workspaceDisabled,
      ["GET", /^\/projects$/, () => json(page([]))],
    ]);
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create your first project" }));
    expect(screen.getByRole("dialog", { name: "New project" })).toBeInTheDocument();
  });

  it("creates a project on the server and opens it", async () => {
    const fetchMock = renderPage(<ProjectsPage />, [
      workspaceDisabled,
      ["GET", /^\/projects$/, () => json(page([]))],
      [
        "POST",
        /^\/projects$/,
        (_, body) => json(makeProject({ id: "new1", ...(body as object) }), 201),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    // Browser-only storage is not offered in the Projects area.
    expect(within(dialog).queryByText("This browser tab")).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Project name"), "  Ledger  ");
    await userEvent.type(within(dialog).getByLabelText(/Description/), "Accounting");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(navigation.router.push).toHaveBeenCalledWith("/app/projects/new1"));
    expect(requestsOf(fetchMock).find((r) => r.method === "POST")?.body).toEqual({
      name: "Ledger",
      description: "Accounting",
    });
  });

  it("validates the name and shows conflicts from the backend", async () => {
    renderPage(<ProjectsPage />, [
      workspaceDisabled,
      ["GET", /^\/projects$/, () => json(page([]))],
      [
        "POST",
        /^\/projects$/,
        () => apiError(409, "project_exists", 'A project named "Ledger" already exists.'),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a project name.");
    await userEvent.type(within(dialog).getByLabelText("Project name"), "a/b");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("cannot contain slashes");
    await userEvent.clear(within(dialog).getByLabelText("Project name"));
    await userEvent.type(within(dialog).getByLabelText("Project name"), "Ledger");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(await within(dialog).findByText(/already exists/)).toBeInTheDocument();
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  it("reports load failures with a retry", async () => {
    renderPage(<ProjectsPage />, [
      workspaceDisabled,
      [
        "GET",
        /^\/projects$/,
        () => apiError(503, "database_unavailable", "The database is currently unavailable."),
      ],
    ]);
    expect(await screen.findByText("Unable to load projects")).toBeInTheDocument();
    expect(screen.getByText("The database is currently unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("ProjectDetailPage", () => {
  const files = [
    {
      id: "f1",
      project_id: "p1",
      path: "src/app.py",
      name: "app.py",
      language: "python",
      size: 40,
      line_count: 4,
      content_hash: "h",
      has_content: true,
      created_at: "2026-09-20T10:00:00Z",
      updated_at: "2026-09-20T10:00:00Z",
    },
  ];

  it("shows the project, its statistics, and files that open in Coding", async () => {
    renderPage(<ProjectDetailPage projectId="p1" />, [
      ["GET", /^\/projects\/p1$/, () => json(makeProject())],
      ["GET", /^\/projects\/p1\/files$/, () => json({ ...page(files), limit: 5000 })],
      [
        "GET",
        /^\/projects\/p1\/intelligence$/,
        () => apiError(404, "not_analyzed", "This project has not been analyzed yet."),
      ],
    ]);
    expect(await screen.findByRole("heading", { name: "Payments service" })).toBeInTheDocument();
    expect(screen.getByText("Billing and invoices")).toBeInTheDocument();
    // The page leads with a question box; details are shown on request.
    expect(screen.getByRole("region", { name: "Ask about this project" })).toBeInTheDocument();
    expect(screen.queryByText("Never")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Show project details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide project details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Never")).toBeInTheDocument(); // last analysis
    expect(screen.getByRole("link", { name: "app.py" })).toHaveAttribute(
      "href",
      "/app/coding?project=p1&file=src%2Fapp.py",
    );
    expect(screen.getByRole("link", { name: /Open in Coding/ })).toHaveAttribute(
      "href",
      "/app/coding?project=p1",
    );
    expect(screen.getByRole("link", { name: /History/ })).toHaveAttribute(
      "href",
      "/app/history?project=p1",
    );
    expect(
      screen.getByText("Analyze the project to list symbols for each file."),
    ).toBeInTheDocument();
  });

  it("does not reveal whether another user's project exists", async () => {
    renderPage(<ProjectDetailPage projectId="someone-elses" />, [
      ["GET", /^\/projects\//, () => apiError(404, "project_not_found", "Project not found.")],
    ]);
    expect(await screen.findByText("Project not found")).toBeInTheDocument();
    expect(screen.getByText(/belongs to another account/)).toBeInTheDocument();
  });

  it("runs project analysis and reloads", async () => {
    let analyzed = false;
    const fetchMock = renderPage(<ProjectDetailPage projectId="p1" />, [
      [
        "GET",
        /^\/projects\/p1$/,
        () =>
          json(
            makeProject({
              stats: {
                ...makeProject().stats,
                last_analyzed_at: analyzed ? new Date().toISOString() : null,
              },
            }),
          ),
      ],
      ["GET", /^\/projects\/p1\/files$/, () => json(page(files))],
      [
        "GET",
        /^\/projects\/p1\/intelligence$/,
        () => apiError(404, "not_analyzed", "Not analyzed."),
      ],
      [
        "POST",
        /^\/projects\/p1\/analyze$/,
        () => {
          analyzed = true;
          return apiError(500, "internal_error", "boom"); // result is re-read from the server
        },
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /Analyze/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(requestsOf(fetchMock).some((r) => r.path === "/projects/p1/analyze")).toBe(true);
  });
});
