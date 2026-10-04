/**
 * Public (browser-visible) runtime configuration.
 *
 * Only NEXT_PUBLIC_* variables may be read here; they are inlined at build
 * time, so never put secrets in them.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";

/**
 * An absolute http(s) URL (development: the backend on another port), or a same-origin path
 * such as "/api/v1" (behind the reverse proxy, where one image serves any domain).
 */
export function parseApiBaseUrl(raw: string | undefined): string {
  const value = (raw ?? "").trim() || DEFAULT_API_BASE_URL;
  if (value.startsWith("/") && !value.startsWith("//") && !/[\s\\]/.test(value)) {
    return value.replace(/\/+$/, "");
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("bad protocol");
    return url.toString().replace(/\/+$/, "");
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL must be an absolute http(s) URL or a path such as /api/v1, received ${JSON.stringify(value)}`,
    );
  }
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const appConfig = {
  apiBaseUrl: parseApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL),
  apiTimeoutMs: parsePositiveInt(process.env.NEXT_PUBLIC_API_TIMEOUT_MS, 10_000),
  healthPollIntervalMs: parsePositiveInt(process.env.NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS, 15_000),
} as const;
