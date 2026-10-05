// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, type ReactElement } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { fakeBackend, json, makeProject, page, requestsOf, type Route } from "@/testing/fake-api";
import { navigation } from "@/testing/next-navigation";

import { UploadDetailPage } from "./upload-detail-page";
import { UploadsPage } from "./uploads-page";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

const UPLOAD = makeProject({
  id: "u1",
  name: "atharva",
  origin: "upload",
  description: "Uploaded from the local folder “atharva”.",
  stats: {
    file_count: 2,
    total_bytes: 40,
    total_lines: 4,
    languages: [{ language: "python", files: 2 }],
    last_analyzed_at: "2026-10-04T10:00:00Z",
  },
});

const FILES = ["app/main.py", "app/util.py"].map((path, i) => ({
  id: `f${i}`,
  project_id: "u1",
  path,
  name: path.split("/").pop(),
  language: "python",
  size: 20,
  line_count: 2,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-04T10:00:00Z",
  updated_at: "2026-10-04T10:00:00Z",
}));

const ARCHITECTURE = {
  files: 2,
  languages: { python: 2 },
  roles: { source: 2 },
  components: [
    { name: "app", files: 2, symbols: 2, languages: { python: 2 }, roles: { source: 2 } },
  ],
  links: [],
  entry_points: [],
  api_routes: [],
  data_models: [],
  tests: 0,
  truncated: false,
  limitations: ["Roles come from file names."],
};

const agentStatus = (available: boolean): Route => [
  "GET",
  /^\/agent\/status$/,
  () =>
    json({
      available,
      detail: available
        ? null
        : "AI assistance is turned off (set CODEWALK_AI_ENABLED=true to enable it).",
      tools: [],
      max_steps: 8,
      max_actions: 3,
      max_tool_calls: 12,
      modes: ["assist"],
    }),
];

const detailRoutes = (project = UPLOAD): Route[] => [
  ["GET", /^\/projects\/u1$/, () => json(project)],
  ["GET", /^\/projects\/u1\/files$/, () => json({ ...page(FILES), limit: 5000 })],
  [
    "GET",
    /^\/projects\/u1\/files\/f0$/,
    () => json({ ...FILES[0], content: "import util\nprint(util.x)\n" }),
  ],
  ["GET", /^\/projects\/u1\/architecture$/, () => json(ARCHITECTURE)],
];

beforeAll(() => {
  // jsdom has no <dialog> support.
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  Element.prototype.scrollIntoView = function () {};
});
beforeEach(() => navigation.reset("/app/uploads"));
afterEach(() => vi.unstubAllGlobals());

function renderWith(ui: ReactElement, routes: Route[]) {
  const fetchMock = fakeBackend(routes);
  vi.stubGlobal("fetch", fetchMock);
  render(<WorkspaceProviders>{ui}</WorkspaceProviders>);
  return fetchMock;
}

describe("Uploads page", () => {
  it("lists only uploaded projects", async () => {
    const fetchMock = renderWith(<UploadsPage />, [
      ["GET", /^\/projects$/, () => json(page([UPLOAD]))],
    ]);
    expect(await screen.findByRole("link", { name: /atharva/ })).toHaveAttribute(
      "href",
      "/app/uploads/u1",
    );
    const list = requestsOf(fetchMock).find((r) => r.path === "/projects")!;
    expect(new URLSearchParams(list.search).get("origin")).toBe("upload");
  });

  it("explains the empty state and offers an upload", async () => {
    renderWith(<UploadsPage />, [["GET", /^\/projects$/, () => json(page([]))]]);
    expect(await screen.findByText("No uploads yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload a folder" })).toBeInTheDocument();
  });
});

describe("Upload analysis view", () => {
  it("shows the files and architecture, and opens a file read-only", async () => {
    renderWith(<UploadDetailPage projectId="u1" />, [...detailRoutes(), agentStatus(false)]);
    const files = await screen.findByRole("complementary", { name: "Files" });
    await userEvent.click(within(files).getByRole("button", { name: "app/main.py" }));
    const viewer = await screen.findByRole("region", { name: "File app/main.py" });
    expect(await within(viewer).findByText("print(util.x)")).toBeInTheDocument();
    expect(within(viewer).getByText(/read-only/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(await screen.findByRole("table", { name: "Components" })).toBeInTheDocument();
  });

  it("explains when the agent is unavailable without blocking the other tools", async () => {
    renderWith(<UploadDetailPage projectId="u1" />, [...detailRoutes(), agentStatus(false)]);
    expect(
      await screen.findByText(/Agent unavailable: AI assistance is turned off/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("asks the agent and shows the answer and the files it read, with no proposals", async () => {
    const fetchMock = renderWith(<UploadDetailPage projectId="u1" />, [
      ...detailRoutes(),
      agentStatus(true),
      [
        "POST",
        /^\/agent\/run$/,
        () =>
          json({
            id: "r1",
            project_id: "u1",
            mode: "assist",
            findings: [],
            context: { files_inspected: ["app/util.py"], memory_items: 0 },
            status: "completed",
            message: "What does util do?",
            file_path: null,
            answer: "util.py defines x, which main.py prints.",
            provider: "openai",
            model: "gpt-5",
            error: null,
            events: [],
            tool_calls: [],
            actions: [],
            warnings: [],
            duration_ms: 1200,
            created_at: "2026-10-04T10:00:00Z",
            completed_at: "2026-10-04T10:00:01Z",
          }),
      ],
    ]);
    const question = await screen.findByLabelText("Your question");
    await waitFor(() => expect(question).toBeEnabled());
    await userEvent.type(question, "What does util do?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByRole("region", { name: "Agent answer" });
    expect(
      within(answer).getByText("util.py defines x, which main.py prints."),
    ).toBeInTheDocument();
    expect(within(answer).getByRole("button", { name: "app/util.py" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply|Review diff/ })).not.toBeInTheDocument();
    const body = requestsOf(fetchMock).find((r) => r.path === "/agent/run")!.body as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({ project_id: "u1", message: "What does util do?", mode: "assist" });
  });

  it("analyzes a fresh upload once when it is opened", async () => {
    const fresh = { ...UPLOAD, stats: { ...UPLOAD.stats, last_analyzed_at: null } };
    const fetchMock = renderWith(<UploadDetailPage projectId="u1" />, [
      ...detailRoutes(fresh),
      agentStatus(false),
      ["POST", /^\/projects\/u1\/analyze$/, () => json({}, 500)],
    ]);
    await waitFor(() =>
      expect(requestsOf(fetchMock).filter((r) => r.path === "/projects/u1/analyze")).toHaveLength(
        1,
      ),
    );
  });

  it("imports the upload into Coding as an editable copy and opens it", async () => {
    const fetchMock = renderWith(<UploadDetailPage projectId="u1" />, [
      ...detailRoutes(),
      agentStatus(false),
      [
        "POST",
        /^\/projects\/u1\/editable-copy$/,
        () =>
          json(
            makeProject({ id: "c9", name: `${UPLOAD.name} (editable)`, origin: "workspace" }),
            201,
          ),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Open in Coding" }));
    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/app/coding?project=c9"),
    );
    expect(requestsOf(fetchMock).some((r) => r.path === "/projects/u1/editable-copy")).toBe(true);
  });

  it("reports when the import fails and stays on the upload", async () => {
    renderWith(<UploadDetailPage projectId="u1" />, [
      ...detailRoutes(),
      agentStatus(false),
      [
        "POST",
        /^\/projects\/u1\/editable-copy$/,
        () => json({ error: { code: "project_exists", message: "Too many projects." } }, 409),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Open in Coding" }));
    expect(await screen.findByText("Too many projects.")).toBeInTheDocument();
    expect(navigation.router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Open in Coding" })).toBeEnabled();
  });

  it("does not show workspace projects", async () => {
    renderWith(<UploadDetailPage projectId="u1" />, [
      ...detailRoutes({ ...UPLOAD, origin: "workspace" }),
      agentStatus(false),
    ]);
    expect(await screen.findByText("Not an uploaded project")).toBeInTheDocument();
  });
});

describe("Coding workspace", () => {
  it("never opens an uploaded project", async () => {
    const results: boolean[] = [];
    function Probe() {
      const { actions } = useWorkspace();
      useEffect(() => {
        void actions.openServerProject(UPLOAD).then((opened) => results.push(opened));
      }, [actions]);
      return null;
    }
    renderWith(<Probe />, []);
    await waitFor(() => expect(results).toEqual([false]));
  });
});
