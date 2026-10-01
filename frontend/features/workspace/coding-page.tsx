"use client";

import { X } from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";

import { useCodingDeepLink } from "./use-coding-deep-link";
import { CodingWorkspace } from "./workspace";

export function CodingPage() {
  const { error, dismiss } = useCodingDeepLink();
  return (
    <div className="flex h-full min-h-0 flex-col">
      {error && (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-2 border-b border-danger/40 bg-danger/10 px-3 py-1 text-xs text-danger"
        >
          <span className="flex-1">{error}</span>
          <IconButton label="Dismiss" onClick={dismiss}>
            <X aria-hidden className="size-3.5" />
          </IconButton>
        </div>
      )}
      <div className="min-h-0 flex-1">
        <CodingWorkspace />
      </div>
    </div>
  );
}
