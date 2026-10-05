/**
 * Inline AI completion (ghost text): when to ask, and how to ask without flooding the provider.
 *
 * Deterministic diagnostics run on every edit; AI completions do not. A request is made only after
 * typing pauses (debounce), only at a useful position (end of the meaningful text of a line, the
 * start of a block, or after an actionable comment), is cancelled when the editor moves on, is
 * never sent twice for the same context, and stops for a while after the provider refuses (quota,
 * credentials, rate limits) instead of being retried on every keystroke.
 */

import { isApiError } from "@/services/api/errors";

export type CompletionMode = "auto" | "comment";

export interface CompletionInput {
  filePath: string;
  language: string;
  prefix: string;
  suffix: string;
  mode: CompletionMode;
}

export type CompletionFetcher = (input: CompletionInput, signal: AbortSignal) => Promise<string>;

export const COMPLETION_DEBOUNCE_MS = 450;
/** Text sent around the cursor (the server trims further). */
export const COMPLETION_PREFIX_CHARS = 6000;
export const COMPLETION_SUFFIX_CHARS = 2000;
/** After the provider refuses, automatic requests pause this long (or the server's Retry-After). */
export const COMPLETION_BACKOFF_MS = 60_000;

/** Errors after which asking again soon cannot help (or would cost money for nothing). */
const BACKOFF_CODES = new Set([
  "ai_quota_exceeded",
  "ai_auth_failed",
  "ai_model_unavailable",
  "ai_rate_limited",
  "too_many_ai_requests",
  "ai_disabled",
  "ai_not_configured",
]);

const COMMENT = /^\s*(?:#|\/\/|--|\/\*+|\*|<!--)\s*(.*?)\s*(?:\*\/|-->)?\s*$/;
const ACTION_VERBS =
  /^(?:create|add|write|implement|define|make|build|connect|generate|return|calculate|compute|parse|read|load|fetch|validate|sort|convert|handle|initiali[sz]e|set\s*up|setup|open|send|check|get|update|delete|remove|insert|find|filter|print|log|count|merge|split|format|save|store|register|login|log\s*in|hash|encrypt|decrypt|upload|download|test|declare|instantiate|call|use|loop|iterate)\b/i;

/** "# create a function to calculate student average" → true; "# TODO", "# v2" → false. */
export function isActionableComment(line: string): boolean {
  const match = COMMENT.exec(line);
  if (!match) return false;
  const text = match[1].replace(/^(?:todo|fixme|note)\s*:?\s*/i, "");
  return ACTION_VERBS.test(text) && text.split(/\s+/).length >= 3;
}

function isComment(line: string): boolean {
  return COMMENT.test(line) && line.trim() !== "";
}

/**
 * Whether to ask at this position, and how: null when an AI completion is not useful here (inside a
 * word with text after it, on a blank line that does not start a block, or inside a comment).
 * `explicit` (Ctrl+Space) relaxes this to any position.
 */
export function completionModeAt(
  prefix: string,
  lineSuffix: string,
  explicit = false,
): CompletionMode | null {
  const lines = prefix.split("\n");
  const current = lines[lines.length - 1];
  const previous = lines.length > 1 ? lines[lines.length - 2] : "";
  if (current.trim() === "" && isActionableComment(previous)) return "comment";
  if (explicit) return isActionableComment(current) ? "comment" : "auto";
  // Only at the end of the meaningful text of the line (closing brackets/quotes may follow).
  if (!/^[\s)\]}"'`;,]*$/.test(lineSuffix)) return null;
  if (current.trim() === "") {
    // A new, empty line: useful right after something that opens a block.
    return /[:{([]\s*$|=>\s*$|\bdo\s*$/.test(previous) ? "auto" : null;
  }
  if (isComment(current)) return null;
  return "auto";
}

/** Status of AI completions, for the status bar. */
export type CompletionStatus =
  | { state: "idle" }
  | { state: "requesting" }
  | { state: "paused"; code: string; message: string; until: number };

export class InlineCompletionEngine {
  private readonly cache = new Map<string, string>();
  private readonly inflight = new Map<string, Promise<string | null>>();
  private pausedUntil = 0;
  status: CompletionStatus = { state: "idle" };

  constructor(
    private readonly fetcher: CompletionFetcher,
    private readonly options: {
      debounceMs?: number;
      cacheSize?: number;
      backoffMs?: number;
      now?: () => number;
      onStatus?: (status: CompletionStatus) => void;
    } = {},
  ) {}

  private now(): number {
    return this.options.now?.() ?? Date.now();
  }

  private setStatus(status: CompletionStatus): void {
    this.status = status;
    this.options.onStatus?.(status);
  }

  /** Clears a pause (e.g. after the AI settings changed). */
  resume(): void {
    this.pausedUntil = 0;
    this.setStatus({ state: "idle" });
  }

  /** The completion to show, or null (nothing useful, cancelled, paused, or failed). */
  async complete(
    input: CompletionInput,
    { signal, explicit = false }: { signal: AbortSignal; explicit?: boolean },
  ): Promise<string | null> {
    const request: CompletionInput = {
      ...input,
      prefix: input.prefix.slice(-COMPLETION_PREFIX_CHARS),
      suffix: input.suffix.slice(0, COMPLETION_SUFFIX_CHARS),
    };
    // An explicit request (Ctrl+Space) is always attempted; automatic ones wait out a pause.
    if (!explicit && this.now() < this.pausedUntil) return null;
    const key = [
      request.filePath,
      request.mode,
      request.prefix.slice(-800),
      request.suffix.slice(0, 200),
    ].join("\u0000");
    const cached = this.cache.get(key);
    if (cached !== undefined) return cached;
    if (!explicit) {
      const waited = await new Promise<boolean>((resolve) => {
        if (signal.aborted) return resolve(false);
        const timer = setTimeout(
          () => resolve(true),
          this.options.debounceMs ?? COMPLETION_DEBOUNCE_MS,
        );
        signal.addEventListener("abort", () => {
          clearTimeout(timer);
          resolve(false);
        });
      });
      if (!waited) return null;
      // An identical request may have finished while this one waited.
      const answered = this.cache.get(key);
      if (answered !== undefined) return answered;
    }
    const pending = this.inflight.get(key);
    if (pending) return pending; // the same context is already being asked for
    const run = this.fetch(key, request, signal);
    this.inflight.set(key, run);
    try {
      return await run;
    } finally {
      this.inflight.delete(key);
    }
  }

  private async fetch(
    key: string,
    input: CompletionInput,
    signal: AbortSignal,
  ): Promise<string | null> {
    this.setStatus({ state: "requesting" });
    try {
      const text = await this.fetcher(input, signal);
      this.cache.set(key, text);
      if (this.cache.size > (this.options.cacheSize ?? 50))
        this.cache.delete(this.cache.keys().next().value as string);
      this.setStatus({ state: "idle" });
      return text;
    } catch (error) {
      if (signal.aborted || (isApiError(error) && error.kind === "aborted")) {
        this.setStatus({ state: "idle" });
        return null;
      }
      if (isApiError(error) && error.code && BACKOFF_CODES.has(error.code)) {
        this.pausedUntil = this.now() + (this.options.backoffMs ?? COMPLETION_BACKOFF_MS);
        this.setStatus({
          state: "paused",
          code: error.code,
          message: error.message,
          until: this.pausedUntil,
        });
      } else {
        this.setStatus({ state: "idle" });
      }
      return null;
    }
  }
}
