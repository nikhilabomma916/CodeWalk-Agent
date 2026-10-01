// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-context";
import { RequireAuth } from "@/features/auth/auth-guards";
import { WorkspaceProviders } from "@/features/workspace/workspace";
import { fakeBackend, json, requestsOf, testUser } from "@/testing/fake-api";
import { navigation } from "@/testing/next-navigation";

import { AppShell, isActivePath } from "./app-shell";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

afterEach(() => vi.unstubAllGlobals());

function renderShell(pathname: string) {
  navigation.reset(pathname);
  const fetchMock = fakeBackend([
    ["GET", /^\/auth\/me$/, () => json(testUser)],
    ["POST", /^\/auth\/logout$/, () => new Response(null, { status: 204 })],
  ]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <AuthProvider>
      <RequireAuth>
        <WorkspaceProviders>
          <AppShell>
            <p>area content</p>
          </AppShell>
        </WorkspaceProviders>
      </RequireAuth>
    </AuthProvider>,
  );
  return fetchMock;
}

describe("AppShell navigation", () => {
  it("links to the real routes and marks the active one", async () => {
    renderShell("/app/projects/p1");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/app/projects",
      "/app/coding",
      "/app/projects",
      "/app/history",
    ]);
    expect(within(nav).getByRole("link", { name: "Projects" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Coding" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("area content")).toBeInTheDocument();
  });

  it("matches nested routes only on segment boundaries", () => {
    expect(isActivePath("/app/projects/p1", "/app/projects")).toBe(true);
    expect(isActivePath("/app/projects", "/app/projects")).toBe(true);
    expect(isActivePath("/app/projectsx", "/app/projects")).toBe(false);
  });
});

describe("User menu", () => {
  it("shows the account and signs out through the backend", async () => {
    const fetchMock = renderShell("/app/coding");
    await userEvent.click(await screen.findByRole("button", { name: `Account: ${testUser.name}` }));
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(within(menu).getByText(testUser.email)).toBeInTheDocument();
    expect(within(menu).getByText("Member since")).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() =>
      expect(requestsOf(fetchMock)).toContainEqual(
        expect.objectContaining({ method: "POST", path: "/auth/logout" }),
      ),
    );
    // A deliberate sign-out goes to plain /login (no "come back" target).
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/login"));
  });

  it("closes with Escape and returns focus to the button", async () => {
    renderShell("/app/coding");
    const button = await screen.findByRole("button", { name: `Account: ${testUser.name}` });
    await userEvent.click(button);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});
