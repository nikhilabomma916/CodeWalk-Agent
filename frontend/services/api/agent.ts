import { z } from "zod";

import { toBackendDiagnostic } from "./ai";
import { apiClient, type ApiClient } from "./client";

import type { Diagnostic } from "@/types/diagnostics";

/** A run makes several provider calls; the backend bounds it (CODEWALK_AGENT_TIMEOUT_SECONDS, 240 s). */
const AGENT_RUN_TIMEOUT_MS = 300_000;

const permission = z.enum(["read_only", "proposed_change", "write"]);

const statusSchema = z.object({
  available: z.boolean(),
  detail: z.string().nullable(),
  tools: z.array(z.object({ name: z.string(), description: z.string(), permission })),
  max_steps: z.number(),
  max_actions: z.number(),
});
export type AgentStatus = z.infer<typeof statusSchema>;

export const AGENT_EVENT_TYPES = [
  "started",
  "planning",
  "tool_started",
  "tool_completed",
  "tool_failed",
  "tool_denied",
  "action_proposed",
  "response",
  "limit_reached",
  "completed",
  "failed",
] as const;

const eventSchema = z.object({
  type: z.enum(AGENT_EVENT_TYPES),
  message: z.string(),
  at: z.string(),
  tool: z.string().nullable().optional(),
  data: z.record(z.string(), z.unknown()).optional().default({}),
});
export type AgentEvent = z.infer<typeof eventSchema>;

const toolCallSchema = z.object({
  index: z.number(),
  tool: z.string(),
  permission: permission.nullable(),
  arguments: z.record(z.string(), z.unknown()),
  status: z.string(),
  summary: z.string(),
  duration_ms: z.number(),
  error_code: z.string().nullable().optional(),
});
export type AgentToolCall = z.infer<typeof toolCallSchema>;

const changeSchema = z.object({
  file_path: z.string(),
  start_line: z.number(),
  start_column: z.number(),
  end_line: z.number(),
  end_column: z.number(),
  original_text: z.string(),
  replacement_text: z.string(),
});
export type ProposedChange = z.infer<typeof changeSchema>;

export const ACTION_STATUSES = ["pending", "applied", "rejected", "stale"] as const;
export type ActionStatus = (typeof ACTION_STATUSES)[number];

const actionSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  kind: z.string(),
  status: z.enum(ACTION_STATUSES),
  file_path: z.string(),
  summary: z.string(),
  explanation: z.string(),
  changes: z.array(changeSchema),
  diff: z.string(),
  base_content_hash: z.string(),
  validation: z.string(),
  created_at: z.string(),
  decided_at: z.string().nullable(),
  result: z.record(z.string(), z.unknown()),
});
export type AgentAction = z.infer<typeof actionSchema>;

const runSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  status: z.enum(["completed", "limit_reached", "failed"]),
  message: z.string(),
  file_path: z.string().nullable(),
  answer: z.string().nullable(),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
  events: z.array(eventSchema),
  tool_calls: z.array(toolCallSchema),
  actions: z.array(actionSchema),
  warnings: z.array(z.string()),
  duration_ms: z.number(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});
export type AgentRun = z.infer<typeof runSchema>;

const decisionSchema = z.object({
  action: actionSchema,
  file: z
    .object({
      file_id: z.string(),
      path: z.string(),
      content: z.string(),
      content_hash: z.string(),
      version: z.number().nullable(),
    })
    .nullable(),
  diagnostics: z.array(z.record(z.string(), z.unknown())),
});
export type ActionDecision = z.infer<typeof decisionSchema>;

export interface SelectionRange {
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

/** What the agent is told about the editor. The project itself is read server-side by id. */
export interface AgentRunInput {
  projectId: string;
  message: string;
  filePath?: string;
  code?: string;
  selection?: SelectionRange | null;
  diagnostics?: Diagnostic[];
}

export async function getAgentStatus(client: ApiClient = apiClient): Promise<AgentStatus> {
  return (await client.request("/agent/status", { schema: statusSchema })).data;
}

export async function runAgent(
  input: AgentRunInput,
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<AgentRun> {
  const { data } = await client.request("/agent/run", {
    method: "POST",
    body: {
      project_id: input.projectId,
      message: input.message,
      file_path: input.filePath,
      code: input.filePath ? input.code : undefined,
      selection:
        input.filePath && input.selection
          ? {
              start_line: input.selection.startLine,
              start_column: input.selection.startColumn,
              end_line: input.selection.endLine,
              end_column: input.selection.endColumn,
            }
          : undefined,
      diagnostics: (input.diagnostics ?? []).slice(0, 50).map(toBackendDiagnostic),
    },
    schema: runSchema,
    timeoutMs: AGENT_RUN_TIMEOUT_MS,
    signal,
  });
  return data;
}

export async function getAgentRun(runId: string, client: ApiClient = apiClient): Promise<AgentRun> {
  return (await client.request(`/agent/runs/${encodeURIComponent(runId)}`, { schema: runSchema }))
    .data;
}

export async function decideAgentAction(
  actionId: string,
  decision: "approve" | "reject",
  client: ApiClient = apiClient,
): Promise<ActionDecision> {
  const { data } = await client.request(
    `/agent/actions/${encodeURIComponent(actionId)}/${decision}`,
    { method: "POST", schema: decisionSchema, timeoutMs: 60_000 },
  );
  return data;
}

/**
 * Applies a proposal's exact ranges to `content` (the saved file). Returns null when any range no
 * longer holds its original text: the file changed, so the proposal must not be shown as current.
 */
export function applyProposedChanges(content: string, changes: ProposedChange[]): string | null {
  const starts = [0];
  for (const match of content.matchAll(/\r\n|\r|\n/g)) starts.push(match.index + match[0].length);
  const offset = (line: number, column: number) =>
    line - 1 < starts.length ? starts[line - 1] + column - 1 : -1;
  const ranges = changes.map((c) => ({
    start: offset(c.start_line, c.start_column),
    end: offset(c.end_line, c.end_column),
    change: c,
  }));
  for (const r of ranges) {
    if (r.start < 0 || r.end < r.start || content.slice(r.start, r.end) !== r.change.original_text)
      return null;
  }
  let result = content;
  for (const r of [...ranges].sort((a, b) => b.start - a.start)) {
    result = result.slice(0, r.start) + r.change.replacement_text + result.slice(r.end);
  }
  return result;
}
