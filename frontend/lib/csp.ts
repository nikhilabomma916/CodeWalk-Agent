/**
 * Content-Security-Policy for the frontend's HTML responses (set per request by proxy.ts).
 *
 * Scripts: only Next.js scripts carrying this request's nonce run; `'strict-dynamic'` lets
 * them load further scripts (Next.js chunks, Monaco's AMD loader and modules from
 * /monaco/vs), and nothing else. No `'unsafe-inline'` or remote origins for scripts.
 *
 * Exceptions, each required by the editor (see docs/deployment/reverse-proxy.md):
 * - style-src 'unsafe-inline': Monaco creates <style> elements and style attributes at
 *   runtime, which nonces cannot cover. Styles cannot run code.
 * - worker-src blob: Monaco starts its language workers from blob: URLs that load
 *   /monaco/vs/... from this origin.
 * - img-src/font-src data: Monaco's stylesheets embed small icons as data: URIs.
 */

export interface CspOptions {
  nonce: string;
  /** Development needs eval for React's error overlays; production never does. */
  development: boolean;
  /** API base URL (absolute in development, usually "/api/v1" behind the reverse proxy). */
  apiBaseUrl: string;
  /** True when the page was requested over HTTPS (directly or via the proxy). */
  https: boolean;
}

/** The API's origin when it differs from the page's (absolute base URL), else null. */
export function apiOrigin(apiBaseUrl: string): string | null {
  if (apiBaseUrl.startsWith("/")) return null;
  try {
    return new URL(apiBaseUrl).origin;
  } catch {
    return null;
  }
}

export function buildContentSecurityPolicy(options: CspOptions): string {
  const connect = ["'self'"];
  const api = apiOrigin(options.apiBaseUrl);
  if (api) connect.push(api);
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${options.nonce}' 'strict-dynamic'${options.development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  // Only over HTTPS: on plain-HTTP local deployments it would rewrite every request to https.
  if (options.https) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}
