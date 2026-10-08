"use client";

import { createContext, useContext } from "react";

/** Lets parts of the Coding workspace bring a panel into view (e.g. the editor opening the agent). */
export interface WorkspaceLayout {
  showProblems(): void;
  showAgent(): void;
}

const noop: WorkspaceLayout = { showProblems() {}, showAgent() {} };

export const WorkspaceLayoutContext = createContext<WorkspaceLayout>(noop);

export function useWorkspaceLayout(): WorkspaceLayout {
  return useContext(WorkspaceLayoutContext);
}
