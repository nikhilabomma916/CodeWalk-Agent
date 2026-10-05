// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import {
  apiError,
  fakeBackend,
  json,
  makeProject,
  page,
  requestsOf,
  type Route,
} from "@/testing/fake-api";

import { InsightsPanel } from "./insights-panel";

const PATH = "shop/pricing.py";
const FILE = {
  id: "f1",
  project_id: "p1",
  path: PATH,
  name: "pricing.py",
  language: "python",
  size: 10,
  line_count: 2,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const IMPACT = {
  file_path: PATH,
  symbol: "price_of",
  definitions: [
    {
      file_path: PATH,
      lines: [1],
      relationship: "confirmed",
      evidence: "function definition",
      role: null,
      chain: [],
    },
  ],
  same_file_references: [],
  direct_dependents: [
    {
      file_path: "shop/cart.py",
      lines: [1, 5],
      relationship: "confirmed",
      evidence: "imports price_of from the file",
      role: "source",
      chain: [],
    },
  ],
  indirect_dependents: [
    {
      file_path: "shop/api.py",
      lines: [],
      relationship: "confirmed",
      evidence: "imports shop/cart.py, which depends on the target",
      role: "api_route",
      chain: [PATH, "shop/cart.py", "shop/api.py"],
    },
  ],
  possible_references: [
    {
      file_path: "scripts/old.py",
      lines: [3],
      relationship: "possible",
      evidence: "mentions price_of, but no import connects it",
      role: "source",
      chain: [],
    },
  ],
  dependencies: [],
  external_imports: [],
  related_tests: [],
  related_api_routes: [{ file_path: "shop/api.py", line: 4, method: "GET", path: "/cart/total" }],
  truncated: false,
  limitations: ["No call graph."],
};

const ARCHITECTURE = {
  files: 6,
  languages: { python: 6 },
  roles: { source: 4, api_route: 1, test: 1 },
  components: [
    {
      name: "shop",
      files: 5,
      symbols: 4,
      languages: { python: 5 },
      roles: { source: 4, api_route: 1 },
    },
  ],
  links: [{ source: "tests", target: "shop", imports: 1, relationship: "confirmed" }],
  entry_points: [],
  api_routes: [{ file_path: "shop/api.py", line: 4, method: "GET", path: "/cart/total" }],
  data_models: [],
  tests: 1,
  truncated: false,
  limitations: ["Roles come from file names."],
};

function Harness({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.openServerProject(makeProject());
      await actions.openFile(PATH);
    })();
  }, [actions]);
  return state.project && state.buffers[PATH]?.status === "ready" ? <>{children}</> : null;
}

function renderPanel(routes: Route[]) {
  const fetchMock = fakeBackend([
    ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
    [
      "GET",
      /^\/projects\/p1\/files\/f1$/,
      () => json({ ...FILE, content: "def price_of(item):\n    return item.price\n" }),
    ],
    ...routes,
  ]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Harness>
        <InsightsPanel />
      </Harness>
    </WorkspaceProviders>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("Insights panel", () => {
  it("analyzes the impact of the open file and labels confirmed and possible relationships", async () => {
    const fetchMock = renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items: [], limit: 50 })],
      ["POST", /^\/projects\/p1\/impact$/, () => json(IMPACT)],
    ]);
    await userEvent.type(await screen.findByLabelText("Symbol (optional)"), "price_of");
    await userEvent.click(screen.getByRole("button", { name: "Analyze impact" }));
    const region = screen.getByRole("region", { name: "Impact analysis" });
    expect(await within(region).findByText("Direct dependents (1)")).toBeInTheDocument();
    expect(within(region).getByText(/via shop\/cart\.py/)).toBeInTheDocument();
    expect(within(region).getByText("GET /cart/total", { exact: false })).toBeInTheDocument();
    const possible = within(region).getByText("scripts/old.py:3").closest("li")!;
    expect(within(possible).getByText("possible")).toBeInTheDocument();
    expect(requestsOf(fetchMock).find((r) => r.path === "/projects/p1/impact")!.body).toEqual({
      file_path: PATH,
      symbol: "price_of",
    });
  });

  it("says when the symbol is not defined in the open file instead of claiming no dependents", async () => {
    renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items: [], limit: 50 })],
      [
        "POST",
        /^\/projects\/p1\/impact$/,
        () =>
          json({
            ...IMPACT,
            symbol: "no_such_symbol",
            definitions: [],
            direct_dependents: [],
            indirect_dependents: [],
            possible_references: [],
            related_api_routes: [],
          }),
      ],
    ]);
    await userEvent.type(await screen.findByLabelText("Symbol (optional)"), "no_such_symbol");
    await userEvent.click(screen.getByRole("button", { name: "Analyze impact" }));
    const region = screen.getByRole("region", { name: "Impact analysis" });
    expect(
      await within(region).findByText("This symbol is not defined in the current file."),
    ).toBeInTheDocument();
    expect(
      within(region).queryByText("No other project file depends on it."),
    ).not.toBeInTheDocument();
  });

  it("says nothing depends on a defined symbol only when no dependents are found", async () => {
    renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items: [], limit: 50 })],
      [
        "POST",
        /^\/projects\/p1\/impact$/,
        () =>
          json({
            ...IMPACT,
            direct_dependents: [],
            indirect_dependents: [],
            possible_references: [],
            related_api_routes: [],
          }),
      ],
    ]);
    await userEvent.type(await screen.findByLabelText("Symbol (optional)"), "price_of");
    await userEvent.click(screen.getByRole("button", { name: "Analyze impact" }));
    const region = screen.getByRole("region", { name: "Impact analysis" });
    expect(
      await within(region).findByText("No other project file depends on it."),
    ).toBeInTheDocument();
    expect(within(region).getByText(/Defined at line 1/)).toBeInTheDocument();
    expect(
      within(region).queryByText("This symbol is not defined in the current file."),
    ).not.toBeInTheDocument();
  });

  it("summarizes the architecture on request", async () => {
    renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items: [], limit: 50 })],
      ["GET", /^\/projects\/p1\/architecture$/, () => json(ARCHITECTURE)],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Analyze architecture" }));
    const region = screen.getByRole("region", { name: "Architecture" });
    expect(await within(region).findByRole("table", { name: "Components" })).toBeInTheDocument();
    expect(within(region).getByText(/tests → shop/)).toBeInTheDocument();
    expect(within(region).getByText("Roles come from file names.")).toBeInTheDocument();
  });

  it("saves and deletes project notes and shows why a secret was refused", async () => {
    let items = [
      {
        id: "m1",
        kind: "convention",
        text: "Use Pydantic models.",
        created_at: "2026-10-05T00:00:00Z",
      },
    ];
    const fetchMock = renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items, limit: 50 })],
      [
        "POST",
        /^\/projects\/p1\/memory$/,
        (_url, raw) => {
          const body = raw as { text: string };
          if (body.text.includes("password")) {
            return apiError(
              422,
              "memory_contains_secret",
              "This note looks like it contains a credential.",
            );
          }
          items = [
            ...items,
            { id: "m2", kind: "decision", text: body.text, created_at: "2026-10-05T00:00:00Z" },
          ];
          return json(items[1], 201);
        },
      ],
      [
        "DELETE",
        /^\/projects\/p1\/memory\/m1$/,
        () => {
          items = items.filter((i) => i.id !== "m1");
          return new Response(null, { status: 204 });
        },
      ],
    ]);
    const notes = await screen.findByRole("region", { name: "Project notes for the AI" });
    expect(await within(notes).findByText("Use Pydantic models.")).toBeInTheDocument();
    await userEvent.type(within(notes).getByLabelText("Note text"), "password = hunter2hunter2");
    await userEvent.click(within(notes).getByRole("button", { name: "Save note" }));
    expect(await within(notes).findByRole("alert")).toHaveTextContent(
      "looks like it contains a credential",
    );
    await userEvent.clear(within(notes).getByLabelText("Note text"));
    // The warning described text that is gone; it must not linger over an empty box.
    expect(within(notes).queryByRole("alert")).not.toBeInTheDocument();
    // New content is validated again on save.
    await userEvent.type(within(notes).getByLabelText("Note text"), "db password = s3cretvalue");
    await userEvent.click(within(notes).getByRole("button", { name: "Save note" }));
    expect(await within(notes).findByRole("alert")).toHaveTextContent(
      "looks like it contains a credential",
    );
    await userEvent.clear(within(notes).getByLabelText("Note text"));
    await userEvent.selectOptions(within(notes).getByLabelText("Note kind"), "decision");
    await userEvent.type(
      within(notes).getByLabelText("Note text"),
      "Errors use one ErrorResponse shape.",
    );
    await userEvent.click(within(notes).getByRole("button", { name: "Save note" }));
    expect(
      await within(notes).findByText("Errors use one ErrorResponse shape."),
    ).toBeInTheDocument();
    await userEvent.click(
      within(notes).getByRole("button", { name: "Delete note: Use Pydantic models." }),
    );
    await waitFor(() =>
      expect(within(notes).queryByText("Use Pydantic models.")).not.toBeInTheDocument(),
    );
    expect(
      requestsOf(fetchMock).filter((r) => r.method === "POST" && r.path === "/projects/p1/memory"),
    ).toHaveLength(3);
  });

  it("keeps a credential warning while the text is only edited, not cleared", async () => {
    renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items: [], limit: 50 })],
      [
        "POST",
        /^\/projects\/p1\/memory$/,
        () =>
          apiError(422, "memory_contains_secret", "This note looks like it contains a credential."),
      ],
    ]);
    const notes = await screen.findByRole("region", { name: "Project notes for the AI" });
    const input = within(notes).getByLabelText("Note text");
    await userEvent.type(input, "password = hunter2hunter2");
    await userEvent.click(within(notes).getByRole("button", { name: "Save note" }));
    expect(await within(notes).findByRole("alert")).toBeInTheDocument();
    await userEvent.type(input, "!");
    expect(within(notes).getByRole("alert")).toHaveTextContent(
      "looks like it contains a credential",
    );
  });

  it("moves focus to the next note, then to the note input, after deleting with the keyboard", async () => {
    let items = ["Use Pydantic models.", "Errors use one shape.", "Prefer small PRs."].map(
      (text, i) => ({
        id: `m${i + 1}`,
        kind: "convention",
        text,
        created_at: "2026-10-05T00:00:00Z",
      }),
    );
    renderPanel([
      ["GET", /^\/projects\/p1\/memory$/, () => json({ items, limit: 50 })],
      [
        "DELETE",
        /^\/projects\/p1\/memory\/m\d$/,
        (url) => {
          const id = url.pathname.split("/").pop();
          items = items.filter((i) => i.id !== id);
          return new Response(null, { status: 204 });
        },
      ],
    ]);
    const notes = await screen.findByRole("region", { name: "Project notes for the AI" });
    const deleteButton = (text: string) =>
      within(notes).getByRole("button", { name: `Delete note: ${text}` });

    // Middle note: focus moves to the next note's delete button.
    await within(notes).findByText("Errors use one shape.");
    deleteButton("Errors use one shape.").focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(deleteButton("Prefer small PRs.")).toHaveFocus());

    // Last note: focus moves to the previous one.
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(deleteButton("Use Pydantic models.")).toHaveFocus());

    // Only note: focus moves to the note input.
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(within(notes).getByLabelText("Note text")).toHaveFocus());
    expect(within(notes).getByText("No notes yet.")).toBeInTheDocument();
  });
});
