/** Where signed-in users land when no specific page was requested. */
export const DEFAULT_APP_PATH = "/app/projects";

/**
 * A `?next=` target that is safe to navigate to after signing in: only paths
 * inside the application (never another site, a protocol-relative URL, or the
 * auth pages themselves, which would loop).
 */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/app")) return DEFAULT_APP_PATH;
  if (next.startsWith("//") || next.includes("\\")) return DEFAULT_APP_PATH;
  const rest = next.slice("/app".length);
  if (rest !== "" && !rest.startsWith("/") && !rest.startsWith("?")) return DEFAULT_APP_PATH;
  return next;
}

export function loginPath(next?: string): string {
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
