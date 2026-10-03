import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

export const HISTORY_EVENT_TYPES = [
  "project.created",
  "project.updated",
  "project.deleted",
  "project.analyzed",
  "file.created",
  "file.updated",
  "file.restored",
  "file.deleted",
  "file.analyzed",
  "ai.analyzed",
  "ai.explained",
  "ai.fix_suggested",
] as const;

export type HistoryEventType = (typeof HISTORY_EVENT_TYPES)[number];

const historyEventSchema = z.object({
  id: z.string(),
  event_type: z.enum(HISTORY_EVENT_TYPES),
  project_id: z.string().nullable(),
  project_name: z.string(),
  file_id: z.string().nullable(),
  file_path: z.string().nullable(),
  analysis_id: z.string().nullable(),
  details: z.record(z.string(), z.unknown()),
  created_at: z.string(),
});

export type HistoryEvent = z.infer<typeof historyEventSchema>;

const historyDetailSchema = historyEventSchema.extend({
  project_exists: z.boolean(),
  current_project_name: z.string().nullable(),
  current_file_path: z.string().nullable(),
  analysis: z
    .object({
      id: z.string(),
      analysis_type: z.string(),
      status: z.string(),
      language: z.string().nullable(),
      duration_ms: z.number(),
      diagnostic_count: z.number(),
      severity_counts: z.record(z.string(), z.number()),
      created_at: z.string(),
    })
    .nullable(),
});

export type HistoryEventDetail = z.infer<typeof historyDetailSchema>;

const historyPageSchema = z.object({
  items: z.array(historyEventSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});

export type HistoryPage = z.infer<typeof historyPageSchema>;

export interface HistoryQuery {
  projectId?: string;
  eventTypes?: readonly HistoryEventType[];
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export async function listHistory(
  query: HistoryQuery = {},
  client: ApiClient = apiClient,
): Promise<HistoryPage> {
  const params = new URLSearchParams();
  if (query.projectId) params.set("project_id", query.projectId);
  query.eventTypes?.forEach((type) => params.append("event_type", type));
  params.set("order", query.order ?? "desc");
  params.set("limit", String(query.limit ?? 50));
  params.set("offset", String(query.offset ?? 0));
  return (await client.request(`/history?${params.toString()}`, { schema: historyPageSchema }))
    .data;
}

export async function getHistoryEvent(
  id: string,
  client: ApiClient = apiClient,
): Promise<HistoryEventDetail> {
  return (
    await client.request(`/history/${encodeURIComponent(id)}`, { schema: historyDetailSchema })
  ).data;
}
