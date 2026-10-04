/**
 * Light/dark theme: one attribute on <html> (`data-theme`) selects the token set in globals.css.
 * The preference lives only in this browser (localStorage); without one, the system setting is used.
 */

export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_STORAGE_KEY = "codewalk.theme";
/** Fired on window whenever the applied theme changes (same tab). */
export const THEME_CHANGE_EVENT = "codewalk:theme-change";
const TRANSITION_CLASS = "theme-transition";
const TRANSITION_MS = 200;

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

/** The saved preference, or null when the user has not chosen (or storage is unavailable). */
export function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(value) ? value : null;
  } catch {
    return null;
  }
}

export function systemTheme(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** The theme currently applied to the page. */
export function appliedTheme(): Theme {
  const value = document.documentElement.dataset.theme;
  return isTheme(value) ? value : "dark";
}

export function applyTheme(theme: Theme, { animate = false }: { animate?: boolean } = {}): void {
  const root = document.documentElement;
  if (animate) {
    root.classList.add(TRANSITION_CLASS);
    window.setTimeout(() => root.classList.remove(TRANSITION_CLASS), TRANSITION_MS);
  }
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}

/** Saves the user's choice and applies it immediately (no reload). */
export function setThemePreference(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage blocked: the theme still applies for this page.
  }
  applyTheme(theme, { animate: true });
}

/**
 * Runs in <head> before the first paint (nonce-tagged, see app/layout.tsx), so a light-mode user never
 * sees a dark flash. Kept self-contained: it cannot import anything.
 */
export const THEME_INIT_SCRIPT = `(function(){var d=document.documentElement,t;try{t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)})}catch(e){}if(t!=="light"&&t!=="dark"){try{t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}catch(e){t="dark"}}d.dataset.theme=t;d.style.colorScheme=t})();`;
