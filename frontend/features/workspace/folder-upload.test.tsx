// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  apiError,
  fakeBackend,
  json,
  makeProject,
  requestsOf,
  type Route,
} from "@/testing/fake-api";

import { selectFolder, uploadFolder, UPLOAD_BATCH_FILES } from "./folder-upload";
import { MAX_EDITABLE_FILE_BYTES } from "./sources/types";
import { UploadFolderDialog } from "./upload-folder-dialog";

function folderFile(relativePath: string, content: BlobPart): File {
  const file = new File([content], relativePath.split("/").pop() ?? "file");
  Object.defineProperty(file, "webkitRelativePath", { value: `shop/${relativePath}` });
  return file;
}

type ImportBody = { files: { path: string; content: string }[] };

/** An import route that stores everything except paths in `refuse` (reported as skipped). */
function importRoute(refuse: Record<string, string> = {}): Route {
  return [
    "POST",
    /^\/projects\/p1\/files\/import$/,
    (_url: URL, raw: unknown) => {
      const { files } = raw as ImportBody;
      const created = files
        .filter((f) => !(f.path in refuse))
        .map((f) => ({
          id: f.path,
          project_id: "p1",
          path: f.path,
          name: f.path.split("/").pop(),
          language: "python",
          size: f.content.length,
          line_count: 1,
          content_hash: "h",
          has_content: true,
          created_at: "2026-10-04T00:00:00Z",
          updated_at: "2026-10-04T00:00:00Z",
        }));
      const skipped = files
        .filter((f) => f.path in refuse)
        .map((f) => ({ path: f.path, reason: "exists", message: refuse[f.path] }));
      return json({ created, skipped });
    },
  ];
}

beforeAll(() => {
  // jsdom has no <dialog> support.
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(() => vi.unstubAllGlobals());

describe("selectFolder", () => {
  it("drops dependency folders, credentials, and oversized files before anything is read", () => {
    const selection = selectFolder([
      folderFile("src/main.py", "print(1)\n"),
      folderFile("README.md", "# Shop\n"),
      folderFile("node_modules/x/index.js", "x"),
      folderFile(".git/config", "x"),
      folderFile(".env", "KEY=value"),
      folderFile("data/huge.csv", new Uint8Array(MAX_EDITABLE_FILE_BYTES + 1)),
    ]);
    expect(selection.name).toBe("shop");
    expect(selection.files.map((f) => f.path)).toEqual(["README.md", "src/main.py"]);
    expect(selection.skipped.map((s) => s.path).sort()).toEqual([
      ".env",
      ".git/config",
      "data/huge.csv",
      "node_modules/x/index.js",
    ]);
    expect(selection.totalBytes).toBe("print(1)\n".length + "# Shop\n".length);
  });
});

describe("uploadFolder", () => {
  it("uploads in batches, skips binary files, and merges what the server skipped", async () => {
    const files = Array.from({ length: UPLOAD_BATCH_FILES + 20 }, (_, i) =>
      folderFile(`pkg/m${String(i).padStart(3, "0")}.py`, `x = ${i}\n`),
    );
    files.push(folderFile("pkg/logo.png", new Uint8Array([0x89, 0x50, 0x00, 0x01])));
    const fetchMock = fakeBackend([importRoute({ "pkg/m000.py": "already exists" })]);
    vi.stubGlobal("fetch", fetchMock);
    const progress: number[] = [];

    const outcome = await uploadFolder("p1", selectFolder(files), {
      onProgress: (p) => progress.push(p.done),
    });

    const batches = requestsOf(fetchMock).map((r) => (r.body as ImportBody).files.length);
    expect(batches).toEqual([UPLOAD_BATCH_FILES, 20]);
    expect(outcome.uploaded).toBe(UPLOAD_BATCH_FILES + 20 - 1);
    expect(outcome.skipped).toEqual([
      { path: "pkg/logo.png", reason: "binary file" },
      { path: "pkg/m000.py", reason: "already exists" },
    ]);
    expect(progress.at(-1)).toBe(UPLOAD_BATCH_FILES + 21);
  });

  it("stops between batches when cancelled", async () => {
    const files = Array.from({ length: UPLOAD_BATCH_FILES * 2 }, (_, i) =>
      folderFile(`f${i}.py`, "x\n"),
    );
    const controller = new AbortController();
    const fetchMock = fakeBackend([importRoute()]);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      uploadFolder("p1", selectFolder(files), {
        signal: controller.signal,
        onProgress: () => controller.abort(),
      }),
    ).rejects.toBeDefined();
    expect(requestsOf(fetchMock)).toHaveLength(1);
  });
});

describe("UploadFolderDialog", () => {
  const selection = () =>
    selectFolder([
      folderFile("app/main.py", "print(1)\n"),
      folderFile("app/util.py", "x = 1\n"),
      folderFile(".env", "KEY=value"),
    ]);

  it("creates a project, uploads, reports skipped files, and opens the project", async () => {
    const fetchMock = fakeBackend([
      ["POST", /^\/projects$/, () => json(makeProject({ id: "p1", name: "shop" }), 201)],
      importRoute(),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const onOpenProject = vi.fn(async () => {});
    render(
      <UploadFolderDialog
        selection={selection()}
        server={{ available: true }}
        onClose={() => {}}
        onOpenProject={onOpenProject}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Upload folder to a new project" });
    expect(dialog).toHaveTextContent(/shop: 2 files \(\d+ B\) will be uploaded/);
    expect(within(dialog).getByLabelText("Project name")).toHaveValue("shop");
    await userEvent.click(within(dialog).getByRole("button", { name: "Upload 2 files" }));

    expect(await within(dialog).findByText("Uploaded 2 files to “shop”.")).toBeInTheDocument();
    expect(within(dialog).getByText("1 file skipped")).toBeInTheDocument();
    const requests = requestsOf(fetchMock);
    expect(requests[0]).toMatchObject({
      method: "POST",
      path: "/projects",
      body: { name: "shop" },
    });
    expect((requests[1].body as ImportBody).files.map((f) => f.path)).toEqual([
      "app/main.py",
      "app/util.py",
    ]);

    await userEvent.click(within(dialog).getByRole("button", { name: "Open project" }));
    await waitFor(() =>
      expect(onOpenProject).toHaveBeenCalledWith(expect.objectContaining({ id: "p1" })),
    );
  });

  it("shows the server's error in place and keeps the created project reachable", async () => {
    vi.stubGlobal(
      "fetch",
      fakeBackend([
        ["POST", /^\/projects$/, () => json(makeProject({ id: "p1", name: "shop" }), 201)],
        [
          "POST",
          /^\/projects\/p1\/files\/import$/,
          () => apiError(503, "database_unavailable", "Database unavailable."),
        ],
      ]),
    );
    render(
      <UploadFolderDialog
        selection={selection()}
        server={{ available: true }}
        onClose={() => {}}
        onOpenProject={async () => {}}
      />,
    );
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Upload 2 files" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Database unavailable.");
    expect(within(dialog).getByRole("button", { name: "Open project" })).toBeEnabled();
  });

  it("cannot upload while the server is unavailable", () => {
    render(
      <UploadFolderDialog
        selection={selection()}
        server={{ available: false, reason: "Backend offline." }}
        onClose={() => {}}
        onOpenProject={async () => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Upload 2 files" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Backend offline.");
  });
});
