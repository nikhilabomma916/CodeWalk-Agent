"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { isApiError } from "@/services/api/errors";
import { getProject } from "@/services/api/projects";

import { useWorkspace } from "./workspace-context";

export const CODING_PATH = "/app/coding";

/** Link that opens a server project (and optionally a file and line) in the Coding area. */
export function codingHref(projectId: string, file?: string | null, line?: number): string {
  const params = new URLSearchParams({ project: projectId });
  if (file) params.set("file", file);
  if (file && line) params.set("line", String(line));
  return `${CODING_PATH}?${params.toString()}`;
}

/**
 * Handles `?project=<id>&file=<path>&line=<n>` on the Coding page: opens the
 * project through the shared workspace (asking about unsaved changes first),
 * then the file, and finally removes the parameters from the URL.
 */
export function useCodingDeepLink(): { error: string | null; dismiss(): void } {
  const params = useSearchParams();
  const router = useRouter();
  const { state, actions } = useWorkspace();
  const [error, setError] = useState<string | null>(null);
  const openProjectId = useRef<string | undefined>(undefined);
  const projectId = params.get("project");
  const file = params.get("file");
  const line = Number.parseInt(params.get("line") ?? "", 10);

  useEffect(() => {
    openProjectId.current = state.project?.serverProjectId;
  }, [state.project?.serverProjectId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void (async () => {
      try {
        if (openProjectId.current !== projectId) {
          const project = await getProject(projectId);
          if (cancelled) return;
          if (!(await actions.openServerProject(project))) {
            router.replace(CODING_PATH);
            return;
          }
        }
        if (cancelled) return;
        if (file && Number.isFinite(line) && line > 0) await actions.revealPosition(file, line, 1);
        else if (file) await actions.openFile(file);
      } catch (cause) {
        if (cancelled) return;
        setError(
          isApiError(cause) && cause.status === 404
            ? "That project does not exist or is not yours."
            : "The project could not be opened.",
        );
      }
      if (!cancelled) router.replace(CODING_PATH);
    })();
    return () => {
      cancelled = true;
    };
  }, [actions, file, line, projectId, router]);

  return { error, dismiss: () => setError(null) };
}
