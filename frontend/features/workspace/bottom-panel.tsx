"use client";

import { X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { IntelligencePanel } from "@/features/intelligence/intelligence-panel";
import { ProblemsPanel, useAllDiagnostics } from "@/features/problems/problems-panel";

type PanelTab = "problems" | "project";
const TABS: PanelTab[] = ["problems", "project"];

export function BottomPanel({ onClose }: { onClose(): void }) {
  const [tab, setTab] = useState<PanelTab>("problems");
  const { counts } = useAllDiagnostics();

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next =
      TABS[(TABS.indexOf(tab) + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next);
    document.getElementById(`panel-tab-${next}`)?.focus();
  };

  const tabClass = (active: boolean) =>
    `h-8 px-2 text-[11px] font-semibold tracking-wider uppercase ${
      active ? "text-fg shadow-[inset_0_-1px_0_var(--color-accent)]" : "text-fg-muted hover:text-fg"
    }`;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-sunken">
      <div className="flex h-8 shrink-0 items-center border-b border-border pr-1 pl-1">
        <div role="tablist" aria-label="Panels" className="flex" onKeyDown={onKeyDown}>
          <button
            id="panel-tab-problems"
            type="button"
            role="tab"
            aria-selected={tab === "problems"}
            tabIndex={tab === "problems" ? 0 : -1}
            onClick={() => setTab("problems")}
            className={tabClass(tab === "problems")}
          >
            Problems{" "}
            {counts.error + counts.warning + counts.other > 0 &&
              `(${counts.error + counts.warning + counts.other})`}
          </button>
          <button
            id="panel-tab-project"
            type="button"
            role="tab"
            aria-selected={tab === "project"}
            tabIndex={tab === "project" ? 0 : -1}
            onClick={() => setTab("project")}
            className={tabClass(tab === "project")}
          >
            Project
          </button>
        </div>
        <span className="flex-1" />
        <IconButton label="Close panel" shortcut="Ctrl+J" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </IconButton>
      </div>
      <div role="tabpanel" aria-labelledby={`panel-tab-${tab}`} className="min-h-0 flex-1">
        {tab === "problems" ? <ProblemsPanel /> : <IntelligencePanel />}
      </div>
    </div>
  );
}
