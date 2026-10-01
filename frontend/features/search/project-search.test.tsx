// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { fakeBackend, json, makeProject, page, requestsOf, type Route } from "@/testing/fake-api";

import { ProjectSearch } from "./project-search";

const FILE = {
  id: "f1",
  project_id: "p1",
  path: "src/auth/service.py",
  name: "service.py",
  language: "python",
  size: 120,
  line_count: 12,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const RESULT = {
  file_path: "src/auth/service.py",
  symbol_name: "authenticate_user",
  symbol_type: "method",
  qualified_name: "UserService.authenticate_user",
  language: "python",
  line: 7,
  end_line: 9,
  column: 5,
  score: 100,
  score_details: { base: 100, coverage: 1, context_bonus: 0 },
  match_type: "symbol_exact",
  match_reason: "method name equals the query",
  snippet: {
    file_path: "src/auth/service.py",
    start_line: 7,
    end_line: 9,
    lines: ["    def authenticate_user(self):"],
    truncated: false,
  },
  related_symbols: ["UserService"],
};

const projectRoutes: Route[] = [
  ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
  [
    "GET",
    /^\/projects\/p1\/files\/f1$/,
    () => json({ ...FILE, content: "class UserService:\n    pass\n" }),
  ],
  [
    "GET",
    /^\/ai\/status$/,
    () =>
      json({
        enabled: false,
        configured: false,
        available: false,
        provider: null,
        model: null,
        detail: "off",
        analysis_types: [],
      }),
  ],
];

function ServerProject({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void actions.openServerProject(makeProject());
  }, [actions]);
  return (
    <>
      <div data-testid="active">{state.activePath ?? ""}</div>
      <div data-testid="reveal">
        {state.reveal ? `${state.reveal.path}:${state.reveal.line}:${state.reveal.column}` : ""}
      </div>
      {state.project ? children : null}
    </>
  );
}

function renderSearch(routes: Route[]) {
  const fetchMock = fakeBackend([...projectRoutes, ...routes]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <ServerProject>
        <ProjectSearch focusSignal={0} />
      </ServerProject>
    </WorkspaceProviders>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("ProjectSearch", () => {
  it("searches the project and opens a result at its location", async () => {
    const fetchMock = renderSearch([
      [
        "POST",
        /^\/projects\/p1\/search$/,
        () =>
          json({
            query: "authenticate_user",
            terms: ["authenticate", "user"],
            results: [RESULT],
            total: 1,
            truncated: false,
            indexed_files: 1,
            ranking: "score = base x coverage + context bonus",
          }),
      ],
    ]);
    await userEvent.type(
      await screen.findByRole("searchbox", { name: "Search project" }),
      "authenticate_user",
    );
    const results = await screen.findByRole("list", { name: "Search results" });
    expect(within(results).getByText("src/auth/service.py")).toBeInTheDocument();
    expect(within(results).getByText("UserService.authenticate_user")).toBeInTheDocument();
    expect(within(results).getByText("Line 7")).toBeInTheDocument();
    expect(screen.getByText("1 result in 1 file")).toBeInTheDocument();

    // Debounced: one request for the whole query, with the filters.
    const searches = requestsOf(fetchMock).filter((r) => r.path === "/projects/p1/search");
    expect(searches).toHaveLength(1);
    expect(searches[0].body).toMatchObject({ query: "authenticate_user", filters: {} });

    await userEvent.click(
      within(results).getByRole("button", { name: /UserService.authenticate_user/ }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("active").textContent).toBe("src/auth/service.py"),
    );
    expect(screen.getByTestId("reveal").textContent).toBe("src/auth/service.py:7:5");
  });

  it("sends filters and shows when nothing matches", async () => {
    const fetchMock = renderSearch([
      [
        "POST",
        /^\/projects\/p1\/search$/,
        () =>
          json({
            query: "zzz",
            terms: ["zzz"],
            results: [],
            total: 0,
            truncated: false,
            indexed_files: 1,
            ranking: "",
          }),
      ],
    ]);
    await userEvent.selectOptions(await screen.findByLabelText("Symbol type"), "class");
    await userEvent.selectOptions(screen.getByLabelText("Language"), "python");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search project" }), "zzz");
    expect(await screen.findByText("No matches.")).toBeInTheDocument();
    const sent = requestsOf(fetchMock)
      .filter((r) => r.path === "/projects/p1/search")
      .at(-1)!;
    expect(sent.body.filters).toEqual({ language: "python", symbol_type: "class" });
  });

  it("shows search errors (for example, another user's project)", async () => {
    renderSearch([
      [
        "POST",
        /^\/projects\/p1\/search$/,
        () => json({ error: { code: "project_not_found", message: "Project not found." } }, 404),
      ],
    ]);
    await userEvent.type(
      await screen.findByRole("searchbox", { name: "Search project" }),
      "anything",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Project not found.");
  });
});

describe("ProjectSearch without a server project", () => {
  it("explains that search needs a stored project", async () => {
    vi.stubGlobal("fetch", fakeBackend(projectRoutes));
    function Memory({ children }: { children: ReactNode }) {
      const { state, actions } = useWorkspace();
      useEffect(() => {
        if (!state.project) void actions.createProject("Scratch");
      }, [actions, state.project]);
      return state.project ? children : null;
    }
    render(
      <WorkspaceProviders>
        <Memory>
          <ProjectSearch focusSignal={0} />
        </Memory>
      </WorkspaceProviders>,
    );
    expect(
      await screen.findByText(/Project search works on projects stored on the server/),
    ).toBeInTheDocument();
  });
});
