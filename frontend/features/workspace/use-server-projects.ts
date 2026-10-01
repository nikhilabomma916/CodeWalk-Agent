"use client";

import { useCallback, useEffect, useState } from "react";

import type { BackendConnection } from "@/features/backend-status/use-backend-health";
import { databaseStatus } from "@/features/status-bar/status-bar";
import { isApiError } from "@/services/api/errors";
import {
  getWorkspaceFolders,
  listProjects,
  type ServerProject,
  type WorkspaceFolders,
} from "@/services/api/projects";

export type ServerAvailability =
  { available: true } | { available: false; reason: string; checking?: boolean };

/** Whether server-side projects can be used right now, derived from the real health check. */
export function serverAvailability(connection: BackendConnection): ServerAvailability {
  if (connection.state === "checking") {
    return { available: false, reason: "Checking the backend…", checking: true };
  }
  const database = databaseStatus(connection);
  if (!database) return { available: false, reason: "The backend is not reachable." };
  if (database.label === "Database: connected") return { available: true };
  if (database.label === "Database: not configured") {
    return {
      available: false,
      reason: "The server has no database configured (CODEWALK_DATABASE_URL).",
    };
  }
  return { available: false, reason: "The server's database is unavailable." };
}

export type ServerProjectsState =
  | { status: "unavailable"; reason: string }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: ServerProject[]; workspace: WorkspaceFolders };

export function useServerProjects(availability: ServerAvailability) {
  const [state, setState] = useState<ServerProjectsState>({ status: "loading" });
  const available = availability.available;
  const reason = availability.available ? "" : availability.reason;

  const refresh = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [projects, workspace] = await Promise.all([listProjects(), getWorkspaceFolders()]);
      setState({ status: "ready", projects, workspace });
    } catch (error) {
      setState({
        status: "error",
        message: isApiError(error) ? error.message : "Unable to load server projects.",
      });
    }
  }, []);

  useEffect(() => {
    if (!available) return;
    // Fetch in a microtask so the effect body does not set state synchronously.
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [available, refresh]);

  return { state: available ? state : ({ status: "unavailable", reason } as const), refresh };
}
