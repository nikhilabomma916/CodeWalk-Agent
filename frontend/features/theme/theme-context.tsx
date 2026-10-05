"use client";

import { Moon, Sun } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  appliedTheme,
  applyTheme,
  setThemePreference,
  storedTheme,
  systemTheme,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  type Theme,
} from "@/lib/theme";

interface ThemeContextValue {
  theme: Theme;
  setTheme(theme: Theme): void;
  toggleTheme(): void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
}

/** Server render and hydration use the default; the real theme was already applied by the head script. */
const serverTheme = (): Theme => "dark";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, appliedTheme, serverTheme);

  useEffect(() => {
    // Another tab changed the preference: follow it.
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) applyTheme(storedTheme() ?? systemTheme());
    };
    // No saved preference: follow the system setting as it changes.
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    const onSystem = () => {
      if (storedTheme() === null) applyTheme(systemTheme(), { animate: true });
    };
    window.addEventListener("storage", onStorage);
    media?.addEventListener?.("change", onSystem);
    return () => {
      window.removeEventListener("storage", onStorage);
      media?.removeEventListener?.("change", onSystem);
    };
  }, []);

  const setTheme = useCallback((next: Theme) => setThemePreference(next), []);
  const toggleTheme = useCallback(
    () => setThemePreference(appliedTheme() === "dark" ? "light" : "dark"),
    [],
  );
  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** The applied theme. Outside a provider (isolated component tests) it reports "dark" and cannot change. */
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext) ?? { theme: "dark", setTheme: () => {}, toggleTheme: () => {} };
}

/** Switches between light and dark; the accessible name says which theme it switches to. */
export function ThemeToggle({
  className = "",
  showLabel = false,
}: {
  className?: string;
  showLabel?: boolean;
}) {
  const { theme, toggleTheme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  const Icon = next === "light" ? Sun : Moon;
  const label = `Switch to ${next} theme`;
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      title={label}
      className={`inline-flex items-center justify-center gap-1.5 rounded text-fg-muted hover:bg-surface-hover hover:text-fg ${className}`}
    >
      <Icon aria-hidden className="size-4" />
      {showLabel && <span className="text-xs">{next === "light" ? "Light" : "Dark"}</span>}
    </button>
  );
}
