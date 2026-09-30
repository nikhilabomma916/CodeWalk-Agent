import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { createApiClient } from "./client";
import { ApiError } from "./errors";
import { fetchHealth } from "./health";

const schema = z.object({ value: z.number() });

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("Expected the request to fail");
}

describe("createApiClient", () => {
  it("returns parsed data for a valid response", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ value: 7 }, 200, { "X-Request-ID": "abc12345" }),
    );
    const client = createApiClient("http://api.test/api/v1", 1000, fetchImpl);

    const result = await client.request("/thing", { schema });

    expect(result).toEqual({ data: { value: 7 }, status: 200, requestId: "abc12345" });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api.test/api/v1/thing",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends JSON bodies", async () => {
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      jsonResponse({ value: 1 }),
    );
    const client = createApiClient("http://api.test", 1000, fetchImpl);

    await client.request("/thing", { method: "POST", body: { name: "x" }, schema });

    const init = fetchImpl.mock.calls[0][1];
    expect(init?.body).toBe('{"name":"x"}');
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("maps the backend ErrorResponse contract to an http ApiError", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "The request is invalid.",
            request_id: "rid-1",
          },
        },
        422,
      ),
    );
    const error = await captureError(
      createApiClient("http://api.test", 1000, fetchImpl).request("/x", { schema }),
    );

    expect(error.kind).toBe("http");
    expect(error.status).toBe(422);
    expect(error.code).toBe("validation_error");
    expect(error.requestId).toBe("rid-1");
    expect(error.message).toBe("The request is invalid.");
  });

  it("reports non-JSON bodies as malformed", async () => {
    const fetchImpl = vi.fn(async () => new Response("<html>proxy error</html>", { status: 200 }));
    const error = await captureError(
      createApiClient("http://api.test", 1000, fetchImpl).request("/x", { schema }),
    );
    expect(error.kind).toBe("malformed");
  });

  it("reports schema mismatches as malformed", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ value: "not a number" }));
    const error = await captureError(
      createApiClient("http://api.test", 1000, fetchImpl).request("/x", { schema }),
    );
    expect(error.kind).toBe("malformed");
  });

  it("reports connection failures as network errors", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await captureError(
      createApiClient("http://api.test", 1000, fetchImpl).request("/x", { schema }),
    );
    expect(error.kind).toBe("network");
  });

  it("times out slow requests", async () => {
    const fetchImpl = vi.fn(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const error = await captureError(
      createApiClient("http://api.test", 20, fetchImpl).request("/x", { schema }),
    );
    expect(error.kind).toBe("timeout");
  });

  it("distinguishes caller cancellation from timeouts", async () => {
    const fetchImpl = vi.fn(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const controller = new AbortController();
    const pending = createApiClient("http://api.test", 5000, fetchImpl).request("/x", {
      schema,
      signal: controller.signal,
    });
    controller.abort();
    const error = await captureError(pending);
    expect(error.kind).toBe("aborted");
  });
});

describe("fetchHealth", () => {
  const healthBody = {
    status: "unavailable",
    service: "CodeWalk Agent API",
    version: "0.1.0",
    environment: "testing",
    timestamp: "2026-09-30T00:00:00Z",
    uptime_seconds: 1.5,
    checks: [
      { name: "database", status: "fail", required: true, latency_ms: 2, detail: "refused" },
    ],
  };

  it("accepts a 503 health report instead of treating it as a transport failure", async () => {
    const client = createApiClient(
      "http://api.test",
      1000,
      vi.fn(async () => jsonResponse(healthBody, 503)),
    );
    const health = await fetchHealth({}, client);
    expect(health.status).toBe("unavailable");
    expect(health.checks[0].name).toBe("database");
  });
});
