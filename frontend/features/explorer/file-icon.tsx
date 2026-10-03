import {
  File,
  FileCode,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  type LucideIcon,
} from "lucide-react";

import type { LanguageId } from "@/lib/languages";

const LANGUAGE_ICONS: Partial<Record<LanguageId, { icon: LucideIcon; color: string }>> = {
  javascript: { icon: FileCode, color: "text-yellow-300" },
  typescript: { icon: FileCode, color: "text-sky-400" },
  python: { icon: FileCode, color: "text-emerald-400" },
  json: { icon: FileJson, color: "text-amber-300" },
  html: { icon: FileCode, color: "text-orange-400" },
  css: { icon: FileCode, color: "text-blue-400" },
  scss: { icon: FileCode, color: "text-pink-400" },
  java: { icon: FileCode, color: "text-red-400" },
  c: { icon: FileCode, color: "text-indigo-300" },
  cpp: { icon: FileCode, color: "text-indigo-400" },
  go: { icon: FileCode, color: "text-cyan-400" },
  rust: { icon: FileCode, color: "text-orange-300" },
  sql: { icon: FileCode, color: "text-fuchsia-300" },
  markdown: { icon: FileText, color: "text-fg-muted" },
  plaintext: { icon: FileText, color: "text-fg-muted" },
};

export function FileIcon({ language }: { language: LanguageId }) {
  const entry = LANGUAGE_ICONS[language];
  const Icon = entry?.icon ?? File;
  return <Icon aria-hidden className={`size-3.5 shrink-0 ${entry?.color ?? "text-fg-muted"}`} />;
}

export function FolderIcon({ open }: { open: boolean }) {
  const Icon = open ? FolderOpen : Folder;
  return <Icon aria-hidden className="size-3.5 shrink-0 text-fg-muted" />;
}
