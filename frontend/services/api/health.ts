import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

/** Mirrors backend `app.schemas.health`. */
export const healthResponseSchema = z.object({
  status: z.enum(["ok", "degraded", "unavailable"]),
  service: z.string(),
  version: z.string(),
  environment: z.string(),
  timestamp: z.string(),
  uptime_seconds: z.number(),
  checks: z.array(
    z.object({
      name: z.string(),
      status: z.enum(["pass", "fail", "not_configured"]),
      required: z.boolean(),
      latency_ms: z.number(),
      detail: z.string().nullable().optional(),
    }),
  ),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;

export async function fetchHealth(
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
  client: ApiClient = apiClient,
): Promise<HealthResponse> {
  const response = await client.request("/health", {
    schema: healthResponseSchema,
    // 503 carries a valid HealthResponse describing which dependency failed.
    acceptStatuses: [503],
    ...options,
  });
  return response.data;
}
