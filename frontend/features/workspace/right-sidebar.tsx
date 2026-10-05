"use client";

import { X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { AgentPanel } from "@/features/agent/agent-panel";
import { AIReviewPanel } from "@/features/ai/ai-review-panel";
import { FileHistoryPanel } from "@/features/history/file-history-panel";
import { InsightsPanel } from "@/features/insights/insights-panel";
import { IntelligencePanel } from "@/features/intelligence/intelligence-panel";

type AssistantTab = "agent" | "review" | "history" | "insights" | "project";
const TABS: AssistantTab[] = ["agent", "review", "history", "insights", "project"];
const TAB_LABEL: Record<AssistantTab, string> = {
  agent: "Agent",
  review: "AI Review",
  history: "History",
  insights: "Insights",
  project: "Project",
};

/**
 * The Coding workspace's right sidebar: the AI agent (default) and the other AI/project views.
 * The bottom panel is kept for Problems.
 */
export function RightSidebar({ onClose }: { onClose(): void }) {
  const [tab, setTab] = useState<AssistantTab>("agent");

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next =
      TABS[(TABS.indexOf(tab) + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next);
    document.getElementById(`assistant-tab-${next}`)?.focus();
  };

  const tabClass = (active: boolean) =>
    `h-8 px-2 text-[11px] font-semibold tracking-wider uppercase ${
      active ? "text-fg shadow-[inset_0_-1px_0_var(--color-accent)]" : "text-fg-muted hover:text-fg"
    }`;

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border bg-surface-sunken">
      <div className="flex h-8 shrink-0 items-center border-b border-border pr-1 pl-1">
        <div
          role="tablist"
          aria-label="AI and project views"
          className="flex"
          onKeyDown={onKeyDown}
        >
          {TABS.map((id) => (
            <button
              key={id}
              id={`assistant-tab-${id}`}
              type="button"
              role="tab"
              aria-selected={tab === id}
              tabIndex={tab === id ? 0 : -1}
              onClick={() => setTab(id)}
              className={tabClass(tab === id)}
            >
              {TAB_LABEL[id]}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        <IconButton label="Close AI sidebar" shortcut="Ctrl+Alt+B" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </IconButton>
      </div>
      <div
        role="tabpanel"
        aria-labelledby={`assistant-tab-${tab}`}
        className="min-h-0 flex-1 overflow-hidden"
      >
        {tab === "agent" ? (
          <AgentPanel />
        ) : tab === "review" ? (
          <AIReviewPanel />
        ) : tab === "history" ? (
          <FileHistoryPanel />
        ) : tab === "insights" ? (
          <InsightsPanel />
        ) : (
          <IntelligencePanel />
        )}
      </div>
    </div>
  );
}
