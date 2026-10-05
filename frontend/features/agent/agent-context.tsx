"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { errorState, type Remote } from "@/features/ai/ai-assist-context";
import { useCursor, type SelectionInfo } from "@/features/editor/cursor-context";
import { useWorkspace } from "@/features/workspace/workspace-context";
import {
  decideAgentAction,
  decideAgentGroup,
  getAgentStatus,
  runAgent,
  type AgentAction,
  type AgentMode,
  type AgentRun,
  type AgentStatus,
  type ReviewFinding,
} from "@/services/api/agent";
import { isApiError } from "@/services/api/errors";

export interface AskOptions {
  /** Send the open file (its current, possibly unsaved, content) and its problems. */
  includeFile: boolean;
  /** Send the editor selection, when there is one. */
  includeSelection: boolean;
  /** The workflow to run (Module 17); "assist" when omitted. */
  mode?: AgentMode;
}

export type RunState =
  | { state: "idle" }
  | { state: "running"; message: string; startedAt: number }
  | { state: "ready"; run: AgentRun }
  | { state: "error"; message: string; code?: string };

export interface DecisionState {
  state: "busy" | "error";
  message?: string;
}

interface AgentValue {
  status: Remote<AgentStatus>;
  refreshStatus(): Promise<void>;
  run: RunState;
  ask(message: string, options: AskOptions): Promise<void>;
  cancel(): void;
  decisions: Record<string, DecisionState>;
  approve(action: AgentAction): Promise<void>;
  reject(action: AgentAction): Promise<void>;
  /** Approve or reject every file of a multi-file proposal together (keyed "group:<id>"). */
  decideGroup(groupId: string, decision: "approve" | "reject"): Promise<void>;
  /** Ask the agent for a fix for one review finding (a new, separate request). */
  proposeFixFor(finding: ReviewFinding): Promise<void>;
  /** The proposal shown as a diff over the editor, if any. */
  reviewing: AgentAction | null;
  openReview(action: AgentAction): Promise<void>;
  closeReview(): void;
  /** The selection the next request would include (null when none). */
  selection: SelectionInfo | null;
}

const AgentContext = createContext<AgentValue | null>(null);

function messageFor(error: unknown, fallback: string): { message: string; code?: string } {
  if (isApiError(error) && error.code === "too_many_agent_runs")
    return { message: error.message, code: error.code };
  if (isApiError(error) && error.kind === "aborted")
    return {
      message: "Cancelled. The server may still finish this request in the background.",
      code: "cancelled",
    };
  const state = errorState(error, fallback);
  return state.state === "error"
    ? { message: state.message, code: state.code }
    : { message: fallback };
}

export function AgentProvider({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const cursor = useCursor();
  const [status, setStatus] = useState<Remote<AgentStatus>>({ state: "loading" });
  const [run, setRun] = useState<RunState>({ state: "idle" });
  const [decisions, setDecisions] = useState<Record<string, DecisionState>>({});
  const [reviewing, setReviewing] = useState<AgentAction | null>(null);
  const stateRef = useRef(state);
  const controller = useRef<AbortController | null>(null);
  const token = useRef(0);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const selection = cursor?.selection ?? null;
  const selectionRef = useRef(selection);
  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus({ state: "ready", data: await getAgentStatus() });
    } catch (error) {
      setStatus(errorState(error, "Unable to read the agent status."));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void refreshStatus();
    });
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  // A run belongs to one project: clear everything when the project changes or closes.
  const projectKey = state.project?.id;
  const [shownProject, setShownProject] = useState(projectKey);
  if (shownProject !== projectKey) {
    setShownProject(projectKey);
    setRun({ state: "idle" });
    setDecisions({});
    setReviewing(null);
  }
  useEffect(
    () => () => {
      controller.current?.abort();
    },
    [projectKey],
  );

  const ask = useCallback(async (message: string, options: AskOptions) => {
    const current = stateRef.current;
    const projectId = current.project?.serverProjectId;
    const text = message.trim();
    if (!text) return;
    if (!projectId) {
      setRun({
        state: "error",
        message:
          "The agent works on projects stored on the server. Open one from the Projects area.",
      });
      return;
    }
    const path = current.activePath;
    const buffer = path ? current.buffers[path] : undefined;
    const fileReady = options.includeFile && path && buffer?.status === "ready";
    const diagnostics =
      fileReady && path
        ? Object.values(current.diagnostics).flatMap((byFile) => byFile[path] ?? [])
        : [];

    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const mine = ++token.current;
    setRun({ state: "running", message: text, startedAt: Date.now() });
    setReviewing(null);
    try {
      const result = await runAgent(
        {
          projectId,
          message: text,
          filePath: fileReady ? path : undefined,
          code: fileReady ? buffer.content : undefined,
          selection: fileReady && options.includeSelection ? selectionRef.current : null,
          diagnostics,
          mode: options.mode,
        },
        undefined,
        abort.signal,
      );
      if (mine === token.current) setRun({ state: "ready", run: result });
    } catch (error) {
      if (mine === token.current)
        setRun({ state: "error", ...messageFor(error, "The agent request failed.") });
    } finally {
      if (controller.current === abort) controller.current = null;
    }
  }, []);

  const cancel = useCallback(() => controller.current?.abort(), []);

  const replaceAction = useCallback((updated: AgentAction) => {
    setRun((current) =>
      current.state === "ready"
        ? {
            ...current,
            run: {
              ...current.run,
              actions: current.run.actions.map((a) => (a.id === updated.id ? updated : a)),
            },
          }
        : current,
    );
    setReviewing((current) => (current?.id === updated.id ? null : current));
  }, []);

  const decide = useCallback(
    async (action: AgentAction, decision: "approve" | "reject") => {
      setDecisions((current) => ({ ...current, [action.id]: { state: "busy" } }));
      try {
        const result = await decideAgentAction(action.id, decision);
        replaceAction(result.action);
        if (result.file) actions.syncSavedContent(result.file.path, result.file.content);
        if (result.file && result.action.kind === "create_file") void actions.refreshEntries();
        setDecisions(({ [action.id]: _, ...rest }) => rest);
      } catch (error) {
        if (isApiError(error) && error.code === "stale_action") {
          replaceAction({ ...action, status: "stale" });
        }
        const { message } = messageFor(error, `Could not ${decision} the change.`);
        setDecisions((current) => ({ ...current, [action.id]: { state: "error", message } }));
      }
    },
    [actions, replaceAction],
  );

  const decideGroup = useCallback(
    async (groupId: string, decision: "approve" | "reject") => {
      const key = `group:${groupId}`;
      setDecisions((current) => ({ ...current, [key]: { state: "busy" } }));
      try {
        const result = await decideAgentGroup(groupId, decision);
        result.actions.forEach(replaceAction);
        for (const applied of result.files)
          actions.syncSavedContent(applied.file.path, applied.file.content);
        if (result.files.some((f) => !stateRef.current.entries.some((e) => e.path === f.file.path)))
          void actions.refreshEntries();
        setDecisions(({ [key]: _, ...rest }) => rest);
      } catch (error) {
        if (isApiError(error) && error.code === "stale_action") {
          setRun((current) =>
            current.state === "ready"
              ? {
                  ...current,
                  run: {
                    ...current.run,
                    actions: current.run.actions.map((a) =>
                      a.group_id === groupId ? { ...a, status: "stale" } : a,
                    ),
                  },
                }
              : current,
          );
        }
        const { message } = messageFor(error, `Could not ${decision} the change.`);
        setDecisions((current) => ({ ...current, [key]: { state: "error", message } }));
      }
    },
    [actions, replaceAction],
  );

  const proposeFixFor = useCallback(
    (finding: ReviewFinding) =>
      ask(
        `Propose a minimal fix for this review finding (${finding.severity} ${finding.category}): ` +
          `"${finding.title}" at ${finding.file_path}:${finding.start_line}. Evidence: ${finding.evidence}`,
        { includeFile: false, includeSelection: false, mode: "assist" },
      ),
    [ask],
  );

  const openReview = useCallback(
    async (action: AgentAction) => {
      await actions.openFile(action.file_path);
      actions.activateTab(action.file_path);
      setReviewing(action);
    },
    [actions],
  );

  const value = useMemo<AgentValue>(
    () => ({
      status,
      refreshStatus,
      run,
      ask,
      cancel,
      decisions,
      approve: (action) => decide(action, "approve"),
      reject: (action) => decide(action, "reject"),
      decideGroup,
      proposeFixFor,
      reviewing,
      openReview,
      closeReview: () => setReviewing(null),
      selection,
    }),
    [
      ask,
      cancel,
      decide,
      decideGroup,
      decisions,
      openReview,
      proposeFixFor,
      refreshStatus,
      reviewing,
      run,
      selection,
      status,
    ],
  );

  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>;
}

export function useAgent(): AgentValue {
  const value = useContext(AgentContext);
  if (!value) throw new Error("useAgent must be used inside <AgentProvider>");
  return value;
}
