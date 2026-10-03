"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { appConfig } from "@/lib/config";
import { isApiError } from "@/services/api/errors";
import { fetchHealth, type HealthResponse } from "@/services/api/health";

export type BackendConnection =
  | { state: "checking" }
  | { state: "online"; health: HealthResponse; latencyMs: number; checkedAt: Date }
  | { state: "degraded"; health: HealthResponse; latencyMs: number; checkedAt: Date }
  | { state: "unavailable"; health: HealthResponse; checkedAt: Date }
  | { state: "offline" | "timeout" | "error"; message: string; checkedAt: Date };

const HEALTH_TIMEOUT_MS = 5_000;

/**
 * Polls GET /health and reports the real connection state. Polling pauses
 * while the tab is hidden and re-checks immediately when it becomes visible.
 */
export function useBackendHealth(intervalMs: number = appConfig.healthPollIntervalMs) {
  const [connection, setConnection] = useState<BackendConnection>({ state: "checking" });
  const inFlight = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    const started = performance.now();
    try {
      const health = await fetchHealth({ signal: controller.signal, timeoutMs: HEALTH_TIMEOUT_MS });
      const latencyMs = Math.round(performance.now() - started);
      const checkedAt = new Date();
      if (health.status === "ok") setConnection({ state: "online", health, latencyMs, checkedAt });
      else if (health.status === "degraded")
        setConnection({ state: "degraded", health, latencyMs, checkedAt });
      else setConnection({ state: "unavailable", health, checkedAt });
    } catch (error) {
      if (controller.signal.aborted && !(isApiError(error) && error.kind === "timeout")) return;
      const checkedAt = new Date();
      if (isApiError(error)) {
        if (error.kind === "aborted") return;
        if (error.kind === "network")
          setConnection({ state: "offline", message: error.message, checkedAt });
        else if (error.kind === "timeout")
          setConnection({ state: "timeout", message: error.message, checkedAt });
        else setConnection({ state: "error", message: error.message, checkedAt });
      } else {
        setConnection({
          state: "error",
          message: "Unexpected error while checking the backend",
          checkedAt,
        });
      }
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      void check();
      timer = setInterval(() => void check(), intervalMs);
    };
    const stop = () => {
      clearInterval(timer);
      inFlight.current?.abort();
    };
    const onVisibility = () => {
      stop();
      if (document.visibilityState === "visible") start();
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [check, intervalMs]);

  return { connection, recheck: check };
}
