// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiError, fakeBackend, json, requestsOf, testUser, type Route } from "@/testing/fake-api";
import { navigation } from "@/testing/next-navigation";
import { listProjects } from "@/services/api/projects";

import { AuthProvider, useAuth } from "./auth-context";
import { LoginForm, RegisterForm } from "./auth-forms";
import { RedirectIfAuthenticated, RequireAuth } from "./auth-guards";

vi.mock("next/navigation", () => import("@/testing/next-navigation"));

const signedOut: Route = [
  "GET",
  /^\/auth\/me$/,
  () => apiError(401, "not_authenticated", "Sign in to continue."),
];
const signedIn: Route = ["GET", /^\/auth\/me$/, () => json(testUser)];

function renderWithAuth(ui: ReactNode, routes: Route[]) {
  const fetchMock = fakeBackend(routes);
  vi.stubGlobal("fetch", fetchMock);
  render(<AuthProvider>{ui}</AuthProvider>);
  return fetchMock;
}

beforeEach(() => navigation.reset("/login"));
afterEach(() => vi.unstubAllGlobals());

describe("LoginForm", () => {
  it("has labelled fields and validates before calling the backend", async () => {
    const fetchMock = renderWithAuth(<LoginForm />, [signedOut]);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(requestsOf(fetchMock).filter((r) => r.path === "/auth/login")).toHaveLength(0);
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("signs in with normalized email and sends credentials (cookie) with the request", async () => {
    const fetchMock = renderWithAuth(<LoginForm />, [
      signedOut,
      ["POST", /^\/auth\/login$/, () => json(testUser)],
    ]);
    await userEvent.type(screen.getByLabelText("Email"), "  ADA@example.com ");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-7");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() =>
      expect(requestsOf(fetchMock)).toContainEqual(
        expect.objectContaining({
          method: "POST",
          path: "/auth/login",
          body: { email: "ada@example.com", password: "correct-horse-7" },
          credentials: "include",
        }),
      ),
    );
  });

  it("shows the backend's error for wrong credentials and lets the user retry", async () => {
    renderWithAuth(<LoginForm />, [
      signedOut,
      [
        "POST",
        /^\/auth\/login$/,
        () => apiError(401, "invalid_credentials", "Incorrect email or password."),
      ],
    ]);
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("explains when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    render(
      <AuthProvider>
        <LoginForm />
      </AuthProvider>,
    );
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "whatever-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not reachable/);
  });

  it("toggles password visibility", async () => {
    renderWithAuth(<LoginForm />, [signedOut]);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("RegisterForm", () => {
  it("validates password rules and confirmation locally", async () => {
    const fetchMock = renderWithAuth(<RegisterForm />, [signedOut]);
    await userEvent.type(screen.getByLabelText("Name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "onlyletters");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("Include at least one number or symbol.")).toBeInTheDocument();
    expect(screen.getByText("The passwords do not match.")).toBeInTheDocument();
    expect(requestsOf(fetchMock).some((r) => r.path === "/auth/register")).toBe(false);
  });

  it("registers and reports a taken email on the email field", async () => {
    const fetchMock = renderWithAuth(<RegisterForm />, [
      signedOut,
      [
        "POST",
        /^\/auth\/register$/,
        () => apiError(409, "email_taken", "An account with this email already exists."),
      ],
    ]);
    await userEvent.type(screen.getByLabelText("Name"), " Ada ");
    await userEvent.type(screen.getByLabelText("Email"), "Ada@Example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-7");
    await userEvent.type(screen.getByLabelText("Confirm password"), "correct-horse-7");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText(/already exists. Sign in instead/)).toBeInTheDocument();
    expect(requestsOf(fetchMock).find((r) => r.path === "/auth/register")?.body).toEqual({
      name: "Ada",
      email: "ada@example.com",
      password: "correct-horse-7",
    });
  });
});

describe("route guards", () => {
  it("sends signed-out users to /login, keeping where they were going", async () => {
    navigation.reset("/app/history", "project=p1");
    renderWithAuth(<RequireAuth>secret area</RequireAuth>, [signedOut]);
    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith(
        "/login?next=%2Fapp%2Fhistory%3Fproject%3Dp1",
      ),
    );
    expect(screen.queryByText("secret area")).not.toBeInTheDocument();
  });

  it("renders protected content for signed-in users", async () => {
    navigation.reset("/app/projects");
    renderWithAuth(<RequireAuth>secret area</RequireAuth>, [signedIn]);
    expect(await screen.findByText("secret area")).toBeInTheDocument();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it("shows a backend outage instead of redirecting (no sign-in loop)", async () => {
    navigation.reset("/app/projects");
    renderWithAuth(<RequireAuth>secret area</RequireAuth>, [
      [
        "GET",
        /^\/auth\/me$/,
        () => apiError(503, "database_unavailable", "The database is currently unavailable."),
      ],
    ]);
    expect(await screen.findByText("Unable to load CodeWalk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it("sends signed-in users away from the login page to a safe target", async () => {
    navigation.reset("/login", "next=%2Fapp%2Fhistory");
    renderWithAuth(<RedirectIfAuthenticated>login form</RedirectIfAuthenticated>, [signedIn]);
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/app/history"));

    navigation.reset("/login", "next=https%3A%2F%2Fevil.example");
    renderWithAuth(<RedirectIfAuthenticated>login form</RedirectIfAuthenticated>, [signedIn]);
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/app/projects"));
  });

  it("signs the UI out when any request reports an ended session", async () => {
    navigation.reset("/app/projects");
    let sessionValid = true;
    const fetchMock = fakeBackend([
      ["GET", /^\/auth\/me$/, () => json(testUser)],
      [
        "GET",
        /^\/projects$/,
        () =>
          sessionValid
            ? json({ items: [], total: 0, limit: 200, offset: 0 })
            : apiError(401, "not_authenticated", "Sign in to continue."),
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    function Status() {
      const { status, sessionExpired } = useAuth();
      return <p>{`${status}:${sessionExpired}`}</p>;
    }
    render(
      <AuthProvider>
        <Status />
      </AuthProvider>,
    );
    expect(await screen.findByText("authenticated:false")).toBeInTheDocument();
    sessionValid = false;
    await act(async () => {
      await listProjects().catch(() => {});
    });
    expect(await screen.findByText("unauthenticated:true")).toBeInTheDocument();
  });
});
