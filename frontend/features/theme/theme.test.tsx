// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyTheme,
  setThemePreference,
  storedTheme,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
} from "@/lib/theme";

import { ThemeProvider, ThemeToggle } from "./theme-context";

const root = document.documentElement;

function mockSystem(prefersLight: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("light") ? prefersLight : !prefersLight,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

/** Runs the <head> script exactly as the browser does before the first paint. */
function runInitScript() {
  new Function(THEME_INIT_SCRIPT)();
}

afterEach(() => {
  window.localStorage.clear();
  delete root.dataset.theme;
  root.style.colorScheme = "";
  vi.unstubAllGlobals();
});

describe("theme before first paint", () => {
  it("uses the saved preference", () => {
    mockSystem(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    runInitScript();
    expect(root.dataset.theme).toBe("light");
    expect(root.style.colorScheme).toBe("light");
  });

  it("follows the system setting when nothing is saved", () => {
    mockSystem(true);
    runInitScript();
    expect(root.dataset.theme).toBe("light");
    mockSystem(false);
    runInitScript();
    expect(root.dataset.theme).toBe("dark");
  });

  it("ignores an invalid saved value", () => {
    mockSystem(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    runInitScript();
    expect(root.dataset.theme).toBe("dark");
    expect(storedTheme()).toBeNull();
  });
});

describe("theme preference", () => {
  it("is saved in this browser only and applied at once", () => {
    setThemePreference("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(root.dataset.theme).toBe("light");
    // A reload re-applies it from storage.
    delete root.dataset.theme;
    runInitScript();
    expect(root.dataset.theme).toBe("light");
  });
});

describe("ThemeToggle", () => {
  it("switches between dark and light with a descriptive accessible name", async () => {
    mockSystem(false);
    applyTheme("dark");
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const toggle = screen.getByRole("button", { name: "Switch to light theme" });
    await userEvent.click(toggle);
    expect(root.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBe(toggle);

    // Keyboard: Enter on the focused button switches back.
    toggle.focus();
    await userEvent.keyboard("{Enter}");
    expect(root.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toHaveFocus();
  });

  it("follows a change made in another tab", () => {
    mockSystem(false);
    applyTheme("dark");
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    act(() => {
      fireEvent(window, new StorageEvent("storage", { key: THEME_STORAGE_KEY }));
    });
    expect(root.dataset.theme).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
  });
});
