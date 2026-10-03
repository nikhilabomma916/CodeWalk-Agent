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

const RETRIEVAL_ON = {
  enabled: true,
  configured: true,
  available: true,
  provider: "voyage",
  model: "voyage-code-4",
  dimensions: 1024,
  detail: null,
};

const INDEX = (indexed: number, stale: number) => ({
  available: true,
  model: "voyage-code-4",
  indexable_files: indexed + stale,
  indexed_files: indexed,
  stale_files: stale,
  chunks: indexed * 3,
});

const SEMANTIC_ONLY = {
  ...RESULT,
  file_path: "src/auth/routes.py",
  symbol_name: "login",
  symbol_type: "function",
  qualified_name: "login",
  line: 4,
  end_line: 5,
  column: 1,
  score: 0.016129,
  score_details: null,
  match_type: "semantic",
  match_reason: "semantically similar to the query (cosine similarity 0.812)",
  snippet: null,
  related_symbols: [],
  semantic_similarity: 0.812,
  fusion: { rrf_score: 0.016129, k: 60, deterministic_rank: null, semantic_rank: 2 },
};

function searchResponse(results: unknown[], extra: Record<string, unknown> = {}) {
  return json({
    query: "password",
    terms: ["password"],
    results,
    total: results.length,
    truncated: false,
    indexed_files: 3,
    ranking: "hybrid",
    ...extra,
  });
}

describe("ProjectSearch semantic retrieval", () => {
  it("hides semantic controls and sends deterministic searches when retrieval is unavailable", async () => {
    const fetchMock = renderSearch([
      ["POST", /^\/projects\/p1\/search$/, () => searchResponse([RESULT])],
    ]);
    await userEvent.type(
      await screen.findByRole("searchbox", { name: "Search project" }),
      "password",
    );
    await screen.findByRole("list", { name: "Search results" });
    expect(screen.queryByLabelText("Include semantic matches")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Index project/ })).not.toBeInTheDocument();
    const sent = requestsOf(fetchMock).filter((r) => r.path === "/projects/p1/search");
    expect(sent.at(-1)!.body.mode).toBeUndefined();
    expect(requestsOf(fetchMock).some((r) => r.path.endsWith("/rag/index"))).toBe(false);
  });

  it("indexes on request and sends hybrid searches when the toggle is on", async () => {
    let indexed = false;
    const fetchMock = renderSearch([
      ["GET", /^\/rag\/status$/, () => json(RETRIEVAL_ON)],
      ["GET", /^\/projects\/p1\/rag\/index$/, () => json(indexed ? INDEX(3, 0) : INDEX(0, 3))],
      [
        "POST",
        /^\/projects\/p1\/rag\/index$/,
        () => {
          indexed = true;
          return json({
            files_indexed: 3,
            chunks_embedded: 9,
            chunks_reused: 0,
            tokens_used: 420,
            remaining_files: 0,
            status: INDEX(3, 0),
          });
        },
      ],
      [
        "POST",
        /^\/projects\/p1\/search$/,
        (_url, body) =>
          (body as { mode?: string }).mode === "hybrid"
            ? searchResponse(
                [
                  {
                    ...RESULT,
                    fusion: { ...SEMANTIC_ONLY.fusion, deterministic_rank: 1, semantic_rank: 1 },
                    semantic_similarity: 0.9,
                  },
                  SEMANTIC_ONLY,
                ],
                {
                  mode: "hybrid",
                  mode_used: "hybrid",
                  warnings: [],
                },
              )
            : searchResponse([RESULT]),
      ],
    ]);

    expect(await screen.findByText("Semantic index: 0/3 files (3 to update)")).toBeInTheDocument();
    // Nothing is sent to the embedding provider until the developer asks.
    expect(
      requestsOf(fetchMock).some((r) => r.method === "POST" && r.path.endsWith("/rag/index")),
    ).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Index project" }));
    expect(
      await screen.findByText("Indexed 3 file(s): 9 chunk(s) embedded, 0 reused."),
    ).toBeInTheDocument();
    expect(screen.getByText("Semantic index: 3/3 files")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update index" })).toBeDisabled();

    await userEvent.click(screen.getByLabelText("Include semantic matches"));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search project" }), "password");
    const results = await screen.findByRole("list", { name: "Search results" });
    expect(within(results).getByText("semantic")).toBeInTheDocument();
    expect(within(results).getByText("login")).toBeInTheDocument();
    expect(screen.getByText(/hybrid ranking/)).toBeInTheDocument();
    const login = within(results).getByRole("button", { name: /login/ });
    expect(login).toHaveAttribute("title", expect.stringContaining("semantic rank 2"));
    const sent = requestsOf(fetchMock).filter((r) => r.path === "/projects/p1/search");
    expect(sent.at(-1)!.body.mode).toBe("hybrid");

    await userEvent.click(login);
    await waitFor(() =>
      expect(screen.getByTestId("reveal").textContent).toBe("src/auth/routes.py:4:1"),
    );
  });

  it("shows fallback warnings and indexing errors", async () => {
    renderSearch([
      ["GET", /^\/rag\/status$/, () => json(RETRIEVAL_ON)],
      ["GET", /^\/projects\/p1\/rag\/index$/, () => json(INDEX(1, 2))],
      [
        "POST",
        /^\/projects\/p1\/rag\/index$/,
        () =>
          json(
            {
              error: {
                code: "rag_unavailable",
                message: "The embedding provider could not be reached.",
              },
            },
            503,
          ),
      ],
      [
        "POST",
        /^\/projects\/p1\/search$/,
        () =>
          searchResponse([RESULT], {
            mode: "hybrid",
            mode_used: "deterministic",
            warnings: ["Semantic retrieval failed: provider down. Showing deterministic results."],
          }),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Update index" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The embedding provider could not be reached.",
    );
    expect(screen.getByText("Semantic index: 1/3 files (2 to update)")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Include semantic matches"));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search project" }), "password");
    expect(
      await screen.findByText(
        "Semantic retrieval failed: provider down. Showing deterministic results.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/hybrid ranking/)).not.toBeInTheDocument();
  });
});

describe("ProjectSearch request races", () => {
  it("shows the newest query's results even when an older request answers last", async () => {
    const base = fakeBackend(projectRoutes);
    const fetchImpl = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).endsWith("/search")) return base(input, init);
      const body = JSON.parse(String(init?.body));
      const slow = body.query === "authenticate";
      // Like a real fetch: an aborted request rejects instead of resolving.
      return new Promise<Response>((resolve, reject) => {
        const timer = setTimeout(
          () =>
            resolve(
              json({
                query: body.query,
                terms: [body.query],
                results: slow ? [] : [RESULT],
                total: slow ? 0 : 1,
                truncated: false,
                indexed_files: 1,
                ranking: "",
              }),
            ),
          slow ? 600 : 10,
        );
        init?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);
    render(
      <WorkspaceProviders>
        <ServerProject>
          <ProjectSearch focusSignal={0} />
        </ServerProject>
      </WorkspaceProviders>,
    );
    const box = await screen.findByRole("searchbox", { name: "Search project" });
    await userEvent.type(box, "authenticate");
    await new Promise((resolve) => setTimeout(resolve, 350)); // the slow request is now in flight
    await userEvent.type(box, "_user");
    expect(await screen.findByText("1 result in 1 file")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(screen.getByText("1 result in 1 file")).toBeInTheDocument();
    expect(screen.queryByText("No matches.")).not.toBeInTheDocument();
  });
});
