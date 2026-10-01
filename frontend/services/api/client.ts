import { z } from "zod";

import { appConfig } from "@/lib/config";

import { ApiError } from "./errors";

/** Mirrors backend `app.schemas.errors.ErrorResponse`. */
const errorResponseSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().optional(),
    details: z
      .array(
        z.object({
          location: z.array(z.union([z.string(), z.number()])),
          message: z.string(),
          type: z.string(),
        }),
      )
      .optional(),
  }),
});

export interface RequestOptions<T> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  schema: z.ZodType<T>;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Non-2xx statuses whose body still follows `schema` (e.g. 503 from /health). */
  acceptStatuses?: readonly number[];
}

export interface ApiResponse<T> {
  data: T;
  status: number;
  requestId?: string;
}

export interface ApiClient {
  request<T>(path: string, options: RequestOptions<T>): Promise<ApiResponse<T>>;
}

type SessionEndedListener = () => void;
const sessionEndedListeners = new Set<SessionEndedListener>();

/**
 * Called whenever the backend rejects a request because the session is missing
 * or expired (HTTP 401 `not_authenticated`). The auth state uses this to sign
 * the user out of the UI wherever the request came from.
 */
export function onSessionEnded(listener: SessionEndedListener): () => void {
  sessionEndedListeners.add(listener);
  return () => sessionEndedListeners.delete(listener);
}

export function createApiClient(
  baseUrl: string = appConfig.apiBaseUrl,
  defaultTimeoutMs: number = appConfig.apiTimeoutMs,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): ApiClient {
  async function request<T>(path: string, options: RequestOptions<T>): Promise<ApiResponse<T>> {
    const { method = "GET", body, schema, signal, timeoutMs = defaultTimeoutMs } = options;
    const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;

    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const abortFromCaller = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", abortFromCaller, { once: true });

    let response: Response;
    try {
      response = await fetchImpl(url, {
        method,
        headers:
          body === undefined
            ? { Accept: "application/json" }
            : { Accept: "application/json", "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
        // Send the httpOnly session cookie set by the backend (a different port/origin in development).
        credentials: "include",
      });
    } catch (cause) {
      if (timedOut)
        throw new ApiError("timeout", `Request timed out after ${timeoutMs} ms`, { cause });
      if (signal?.aborted) throw new ApiError("aborted", "Request was cancelled", { cause });
      throw new ApiError("network", "Unable to reach the CodeWalk backend", { cause });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abortFromCaller);
    }

    const requestId = response.headers.get("X-Request-ID") ?? undefined;
    let payload: unknown;
    try {
      const text = await response.text();
      payload = text ? JSON.parse(text) : undefined;
    } catch (cause) {
      throw new ApiError("malformed", "The backend returned a response that is not valid JSON", {
        status: response.status,
        requestId,
        cause,
      });
    }

    const accepted = response.ok || (options.acceptStatuses ?? []).includes(response.status);
    if (!accepted) {
      const parsedError = errorResponseSchema.safeParse(payload);
      if (parsedError.success) {
        const { code, message, request_id } = parsedError.data.error;
        if (response.status === 401 && code === "not_authenticated") {
          sessionEndedListeners.forEach((listener) => listener());
        }
        throw new ApiError("http", message, {
          status: response.status,
          code,
          requestId: request_id ?? requestId,
        });
      }
      throw new ApiError("http", `The backend responded with HTTP ${response.status}`, {
        status: response.status,
        requestId,
      });
    }

    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new ApiError("malformed", "The backend response did not match the expected format", {
        status: response.status,
        requestId,
        cause: parsed.error,
      });
    }
    return { data: parsed.data, status: response.status, requestId };
  }

  return { request };
}

export const apiClient = createApiClient();
