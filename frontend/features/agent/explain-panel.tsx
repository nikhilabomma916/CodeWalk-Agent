"use client";

import { useWorkspace } from "@/features/workspace/workspace-context";

import { ProjectExplain } from "./project-explain";

/** Coding sidebar "Explain" tab: the project explanation for the open server project. */
export function ExplainProjectPanel() {
  const { state, actions } = useWorkspace();
  const projectId = state.project?.serverProjectId;
  if (!projectId)
    return (
      <p className="p-3 text-xs text-fg-muted">
        Project explanation works on projects stored on CodeWalk. Save this project to CodeWalk
        (Agent tab) or open one from Projects.
      </p>
    );
  return (
    <div className="h-full overflow-y-auto p-3">
      <ProjectExplain
        projectId={projectId}
        compact
        onOpen={(path, line) => void actions.revealPosition(path, line, 1)}
      />
    </div>
  );
}
