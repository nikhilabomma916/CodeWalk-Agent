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
  max_tool_calls: z.number().optional().default(0),
  modes: z.array(z.string()).optional().default([]),
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
  group_id: z.string().nullable().optional().default(null),
  group_size: z.number().optional().default(1),
  confidence: z.string().nullable().optional().default(null),
  risk: z.string().nullable().optional().default(null),
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

/** Module 17: the workflows the agent can run. */
export const AGENT_MODES = [
  "assist",
  "review",
  "tests",
  "docs",
  "refactor",
  "impact",
  "architecture",
  "explain",
] as const;
export type AgentMode = (typeof AGENT_MODES)[number];

/** Topics of the project explanation (mode "explain"); the backend accepts exactly these. */
export const EXPLAIN_TOPICS = [
  { id: "overview", label: "Overview" },
  { id: "architecture", label: "Architecture" },
  { id: "how_it_works", label: "How It Works" },
  { id: "file_structure", label: "File Structure" },
  { id: "modules", label: "Modules" },
  { id: "dependencies", label: "Dependencies" },
  { id: "entry_points", label: "Entry Points" },
  { id: "apis", label: "APIs" },
  { id: "database", label: "Database" },
  { id: "data_flow", label: "Data Flow" },
  { id: "authentication", label: "Authentication" },
  { id: "security", label: "Security" },
  { id: "ai_ml", label: "AI/ML" },
  { id: "configuration", label: "Configuration" },
  { id: "testing", label: "Testing" },
  { id: "deployment", label: "Deployment" },
  { id: "risks", label: "Problems / Risks" },
  { id: "improvements", label: "Improvement Suggestions" },
] as const;
export type ExplainTopic = (typeof EXPLAIN_TOPICS)[number]["id"];

export const EXPLAIN_DEPTHS = [
  { id: "beginner", label: "Beginner" },
  { id: "developer", label: "Developer" },
  { id: "technical", label: "Technical" },
  { id: "deep_dive", label: "Deep Dive" },
] as const;
export type ExplainDepth = (typeof EXPLAIN_DEPTHS)[number]["id"];

export const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;
const findingSchema = z.object({
  id: z.string(),
  severity: z.enum(SEVERITIES),
  category: z.string(),
  title: z.string(),
  file_path: z.string(),
  start_line: z.number(),
  end_line: z.number(),
  explanation: z.string(),
  evidence: z.string(),
  suggestion: z.string(),
  confidence: z.string(),
  excerpt: z.array(z.string()),
});
export type ReviewFinding = z.infer<typeof findingSchema>;

const usageSchema = z.object({
  provider_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  tool_calls: z.number(),
  largest_prompt_chars: z.number(),
});

const runSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  mode: z.string().optional().default("assist"),
  findings: z.array(findingSchema).optional().default([]),
  usage: usageSchema.optional(),
  context: z
    .object({ files_inspected: z.array(z.string()), memory_items: z.number() })
    .optional()
    .default({ files_inspected: [], memory_items: 0 }),
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

const actionPageSchema = z.object({
  items: z.array(actionSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});

/** The AI change history of a project, newest first. */
export async function listAgentActions(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<{ items: AgentAction[]; total: number }> {
  const params = new URLSearchParams({ project_id: projectId, limit: "100" });
  const { data } = await client.request(`/agent/actions?${params.toString()}`, {
    schema: actionPageSchema,
  });
  return { items: data.items, total: data.total };
}

const undoSchema = z.object({
  action: actionSchema,
  file: decisionSchema.shape.file,
  deleted: z.boolean(),
});
export type UndoResult = z.infer<typeof undoSchema>;

/** Undoes an applied AI change (only if the file was not changed since). */
export async function undoAgentAction(
  actionId: string,
  client: ApiClient = apiClient,
): Promise<UndoResult> {
  const { data } = await client.request(`/agent/actions/${encodeURIComponent(actionId)}/undo`, {
    method: "POST",
    schema: undoSchema,
    timeoutMs: 60_000,
  });
  return data;
}

const groupDecisionSchema = z.object({
  group_id: z.string(),
  actions: z.array(actionSchema),
  files: z.array(
    z.object({
      action_id: z.string(),
      file: z.object({
        file_id: z.string(),
        path: z.string(),
        content: z.string(),
        content_hash: z.string(),
        version: z.number().nullable(),
      }),
      diagnostic_count: z.number(),
    }),
  ),
});
export type GroupDecision = z.infer<typeof groupDecisionSchema>;

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
  mode?: AgentMode;
  /** Earlier turns of the same chat, oldest first (at most 8 are sent). */
  history?: ConversationTurn[];
  /** Mode "explain" only: the topic and depth (the backend defaults to overview / developer). */
  explainTopic?: ExplainTopic;
  explainDepth?: ExplainDepth;
}

/** One earlier message of a chat: what the developer asked, or what the agent answered. */
export interface ConversationTurn {
  role: "developer" | "agent";
  content: string;
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
      mode: input.mode ?? "assist",
      history: (input.history ?? []).slice(-8),
      ...(input.mode === "explain"
        ? { explain_topic: input.explainTopic, explain_depth: input.explainDepth }
        : {}),
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

/** Approve or reject every file of a multi-file proposal together (Module 17). */
export async function decideAgentGroup(
  groupId: string,
  decision: "approve" | "reject",
  client: ApiClient = apiClient,
): Promise<GroupDecision> {
  const { data } = await client.request(
    `/agent/groups/${encodeURIComponent(groupId)}/${decision}`,
    { method: "POST", schema: groupDecisionSchema, timeoutMs: 60_000 },
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
