"use client";

import { X } from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";
import { ProblemsPanel, useAllDiagnostics } from "@/features/problems/problems-panel";

/**
 * The bottom panel: Problems. AI views (agent, review, insights, project) are in the right sidebar.
 */
export function BottomPanel({ onClose }: { onClose(): void }) {
  const { counts } = useAllDiagnostics();
  const total = counts.error + counts.warning + counts.other;
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-sunken">
      <div className="flex h-8 shrink-0 items-center border-b border-border pr-1 pl-1">
        <div role="tablist" aria-label="Panels" className="flex">
          <button
            id="panel-tab-problems"
            type="button"
            role="tab"
            aria-selected
            className="h-8 px-2 text-[11px] font-semibold tracking-wider text-fg uppercase shadow-[inset_0_-1px_0_var(--color-accent)]"
          >
            Problems{total > 0 && ` (${total})`}
          </button>
        </div>
        <span className="flex-1" />
        <IconButton label="Close panel" shortcut="Ctrl+J" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </IconButton>
      </div>
      <div role="tabpanel" aria-labelledby="panel-tab-problems" className="min-h-0 flex-1">
        <ProblemsPanel />
      </div>
    </div>
  );
}
