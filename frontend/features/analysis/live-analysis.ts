import type { AnalysisOutcome, BackendLanguage } from "@/services/api/analysis";

export interface LiveAnalysisRequest {
  path: string;
  content: string;
  language?: BackendLanguage;
}

export type AnalyzeFn = (
  request: LiveAnalysisRequest,
  signal: AbortSignal,
) => Promise<AnalysisOutcome>;

export interface LiveAnalysisCallbacks {
  /** A request is waiting for the debounce delay. */
  onPending(path: string): void;
  onStart(path: string): void;
  onResult(path: string, outcome: AnalysisOutcome): void;
  onError(path: string, error: unknown): void;
}

export const DEFAULT_ANALYSIS_DELAY_MS = 450;

/**
 * Debounced, cancellable real-time analysis.
 *
 * - Each edit restarts the debounce timer.
 * - A new edit immediately aborts the in-flight request for older content.
 * - A sequence token guarantees that a late response for older content can
 *   never be applied over a newer result, even if abort is not honored.
 */
export class LiveAnalysisScheduler {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private controller: AbortController | undefined;
  private sequence = 0;

  constructor(
    private readonly analyze: AnalyzeFn,
    private readonly callbacks: LiveAnalysisCallbacks,
    private readonly delayMs: number = DEFAULT_ANALYSIS_DELAY_MS,
  ) {}

  schedule(request: LiveAnalysisRequest): void {
    this.cancel();
    const token = this.sequence;
    this.callbacks.onPending(request.path);
    this.timer = setTimeout(() => void this.run(request, token), this.delayMs);
  }

  /** Drop any pending or in-flight analysis. */
  cancel(): void {
    this.sequence += 1;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.controller?.abort();
    this.controller = undefined;
  }

  dispose(): void {
    this.cancel();
  }

  private async run(request: LiveAnalysisRequest, token: number): Promise<void> {
    if (token !== this.sequence) return;
    const controller = new AbortController();
    this.controller = controller;
    this.callbacks.onStart(request.path);
    try {
      const outcome = await this.analyze(request, controller.signal);
      if (token === this.sequence && !controller.signal.aborted) {
        this.callbacks.onResult(request.path, outcome);
      }
    } catch (error) {
      if (token === this.sequence && !controller.signal.aborted) {
        this.callbacks.onError(request.path, error);
      }
    } finally {
      if (this.controller === controller) this.controller = undefined;
    }
  }
}
