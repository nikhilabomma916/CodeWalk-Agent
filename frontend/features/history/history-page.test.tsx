// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fakeBackend,
  json,
  makeEvent,
  makeProject,
  page,
  requestsOf,
  type Route,
} from "@/testing/fake-api";
import { navigation } from "@/testing/next-navigation";

import { HistoryPage } from "./history-page";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

const projects: Route = ["GET", /^\/projects$/, () => json(page([makeProject()]))];

beforeEach(() => navigation.reset("/app/history"));
afterEach(() => vi.unstubAllGlobals());

function renderHistory(routes: Route[]) {
  const fetchMock = fakeBackend([projects, ...routes]);
  vi.stubGlobal("fetch", fetchMock);
  render(<HistoryPage />);
  return fetchMock;
}

describe("HistoryPage", () => {
  it("shows an honest empty state", async () => {
    renderHistory([["GET", /^\/history$/, () => json(page([]))]]);
    expect(await screen.findByText("No activity yet.")).toBeInTheDocument();
  });

  it("groups real events by day", async () => {
    const now = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    renderHistory([
      [
        "GET",
        /^\/history$/,
        () =>
          json(
            page([
              makeEvent({ id: "e2", event_type: "project.analyzed", file_path: null, details: {} }),
              makeEvent({ id: "e1" }),
              makeEvent({
                id: "e0",
                event_type: "project.created",
                file_path: null,
                file_id: null,
                analysis_id: null,
                details: {},
                created_at: yesterday.toISOString(),
              }),
            ]),
          ),
      ],
    ]);
    const today = await screen.findByRole("region", { name: "Today" });
    expect(within(today).getByText("Analyzed project Payments service")).toBeInTheDocument();
    expect(within(today).getByText("Saved src/app.py")).toBeInTheDocument();
    expect(within(today).getByText("· 1 problem")).toBeInTheDocument();
    const before = screen.getByRole("region", { name: "Yesterday" });
    expect(within(before).getByText("Created project Payments service")).toBeInTheDocument();
    expect(screen.getByText("3 events")).toBeInTheDocument();
  });

  it("applies filters from the URL to the API request", async () => {
    navigation.reset("/app/history", "project=p1&type=file.updated");
    const fetchMock = renderHistory([["GET", /^\/history$/, () => json(page([]))]]);
    expect(await screen.findByText("No matching activity.")).toBeInTheDocument();
    const request = requestsOf(fetchMock).find((r) => r.path === "/history")!;
    const params = new URLSearchParams(request.search);
    expect(params.get("project_id")).toBe("p1");
    expect(params.getAll("event_type")).toEqual(["file.updated"]);

    await userEvent.selectOptions(screen.getByLabelText("Activity"), "");
    expect(navigation.router.replace).toHaveBeenCalledWith("/app/history?project=p1");
  });

  it("opens details with links back to the project and file", async () => {
    renderHistory([
      ["GET", /^\/history$/, () => json(page([makeEvent()]))],
      [
        "GET",
        /^\/history\/e1$/,
        () =>
          json({
            ...makeEvent(),
            project_exists: true,
            current_project_name: "Payments service",
            current_file_path: "src/main.py",
            analysis: {
              id: "a1",
              analysis_type: "code",
              status: "completed",
              language: "python",
              duration_ms: 12,
              diagnostic_count: 1,
              severity_counts: { warning: 1 },
              created_at: new Date().toISOString(),
            },
          }),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /Saved src\/app.py/ }));
    const details = await screen.findByRole("complementary", { name: "Activity details" });
    await waitFor(() => expect(within(details).getByText("1 warning")).toBeInTheDocument());
    expect(within(details).getByText("now src/main.py")).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: "Payments service" })).toHaveAttribute(
      "href",
      "/app/projects/p1",
    );
    expect(within(details).getByRole("link", { name: /Open file in Coding/ })).toHaveAttribute(
      "href",
      "/app/coding?project=p1&file=src%2Fmain.py",
    );
  });

  it("marks deleted projects instead of linking to them", async () => {
    const deleted = makeEvent({
      id: "e9",
      event_type: "project.deleted",
      project_id: null,
      file_id: null,
      file_path: null,
      analysis_id: null,
      details: {},
    });
    renderHistory([
      ["GET", /^\/history$/, () => json(page([deleted]))],
      [
        "GET",
        /^\/history\/e9$/,
        () =>
          json({
            ...deleted,
            project_exists: false,
            current_project_name: null,
            current_file_path: null,
            analysis: null,
          }),
      ],
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /Deleted project/ }));
    const details = await screen.findByRole("complementary", { name: "Activity details" });
    expect(await within(details).findByText("(deleted)")).toBeInTheDocument();
    expect(within(details).queryByRole("link")).not.toBeInTheDocument();
  });
});
