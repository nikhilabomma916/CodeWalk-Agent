"use client";

import { Files, Search } from "lucide-react";

import { ProjectExplorer } from "@/features/explorer/project-explorer";
import { ProjectSearch } from "@/features/search/project-search";

export type SidebarView = "explorer" | "search";

interface SidebarProps {
  view: SidebarView;
  onViewChange(view: SidebarView): void;
  /** Changes whenever search is (re)opened, so the query box takes focus. */
  searchFocus: number;
  projectKey: string | undefined;
}

/** The workspace's left column: the file explorer or project search. */
export function Sidebar({ view, onViewChange, searchFocus, projectKey }: SidebarProps) {
  const tab = (id: SidebarView, label: string, Icon: typeof Files, shortcut: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === id}
      title={`${label} (${shortcut})`}
      onClick={() => onViewChange(id)}
      className={`flex h-7 flex-1 items-center justify-center gap-1.5 text-[11px] ${
        view === id
          ? "text-fg shadow-[inset_0_-1px_0_var(--color-accent)]"
          : "text-fg-muted hover:text-fg"
      }`}
    >
      <Icon aria-hidden className="size-3.5" />
      {label}
    </button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-sunken">
      <div role="tablist" aria-label="Sidebar" className="flex shrink-0 border-b border-border">
        {tab("explorer", "Explorer", Files, "Ctrl+Shift+E")}
        {tab("search", "Search", Search, "Ctrl+Shift+F")}
      </div>
      <div className="min-h-0 flex-1" hidden={view !== "explorer"}>
        <ProjectExplorer key={projectKey} />
      </div>
      {view === "search" && (
        <div className="flex min-h-0 flex-1 flex-col">
          <ProjectSearch key={projectKey} focusSignal={searchFocus} />
        </div>
      )}
    </div>
  );
}
