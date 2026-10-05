// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, fakeBackend, json, makeProject, page, requestsOf } from "@/testing/fake-api";

import { isDirty } from "./state";
import { WorkspaceProviders } from "./workspace";
import { AUTO_SAVE_DELAY_MS, useWorkspace } from "./workspace-context";

const FILE = {
  id: "f1",
  project_id: "p1",
  path: "main.py",
  name: "main.py",
  language: "python",
  size: 6,
  line_count: 1,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
};

/** Opens server project p1, opens main.py and exposes an edit button and the buffer state. */
function Probe({ autoSave = true }: { autoSave?: boolean }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    actions.updateSettings({ autoSave });
    void (async () => {
      await actions.openServerProject(makeProject());
      await actions.openFile("main.py");
    })();
  }, [actions, autoSave]);
  const buffer = state.buffers["main.py"];
  return (
    <>
      <output data-testid="state">
        {!buffer || buffer.status !== "ready"
          ? "loading"
          : buffer.saving
            ? "saving"
            : buffer.saveError
              ? "failed"
              : isDirty(buffer)
                ? "unsaved"
                : "saved"}
      </output>
      <button type="button" onClick={() => actions.editFile("main.py", `x = ${Date.now()}\n`)}>
        edit
      </button>
    </>
  );
}

function setup(patch: () => Response, autoSave = true) {
  const fetchMock = fakeBackend([
    ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
    ["GET", /^\/projects\/p1\/files\/f1$/, () => json({ ...FILE, content: "x = 0\n" })],
    ["PATCH", /^\/projects\/p1\/files\/f1$/, patch],
  ]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Probe autoSave={autoSave} />
    </WorkspaceProviders>,
  );
  return fetchMock;
}

const saves = (fetchMock: ReturnType<typeof fakeBackend>) =>
  requestsOf(fetchMock).filter((r) => r.method === "PATCH").length;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Auto save", () => {
  it("saves a changed file once typing has paused", async () => {
    const fetchMock = setup(() => json({ file: { ...FILE, content: "saved" }, analysis: null }));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => screen.getByRole("button", { name: "edit" }).click());
    expect(screen.getByTestId("state")).toHaveTextContent("unsaved");
    // Each edit restarts the timer: no save while typing continues.
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS - 200));
    act(() => screen.getByRole("button", { name: "edit" }).click());
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS - 200));
    expect(saves(fetchMock)).toBe(0);
    await act(async () => vi.advanceTimersByTime(400));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
    expect(saves(fetchMock)).toBe(1);
  });

  it("does nothing when turned off", async () => {
    const fetchMock = setup(() => json({ file: FILE, analysis: null }), false);
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => screen.getByRole("button", { name: "edit" }).click());
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS * 3));
    expect(screen.getByTestId("state")).toHaveTextContent("unsaved");
    expect(saves(fetchMock)).toBe(0);
  });

  it("does not retry a failed save until the file is edited again", async () => {
    const fetchMock = setup(() => apiError(500, "internal_error", "Database unavailable."));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => screen.getByRole("button", { name: "edit" }).click());
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS + 100));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("failed"));
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS * 5));
    expect(saves(fetchMock)).toBe(1); // no retry loop
    act(() => screen.getByRole("button", { name: "edit" }).click());
    expect(screen.getByTestId("state")).toHaveTextContent("unsaved");
    await act(async () => vi.advanceTimersByTime(AUTO_SAVE_DELAY_MS + 100));
    await waitFor(() => expect(saves(fetchMock)).toBe(2));
  });
});
