import { isLanguageId, languageLabel } from "@/lib/languages";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const BACKEND_LANGUAGE_LABELS: Record<string, string> = {
  typescriptreact: "TSX",
  javascriptreact: "JSX",
  plaintext: "Plain text",
};

/** Display name for a backend language id ("python", "typescriptreact", ...). */
export function backendLanguageLabel(language: string): string {
  if (language in BACKEND_LANGUAGE_LABELS) return BACKEND_LANGUAGE_LABELS[language];
  if (isLanguageId(language)) return languageLabel(language);
  return language.charAt(0).toUpperCase() + language.slice(1);
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "3 minutes ago", "yesterday", ... (falls back to "just now" under a minute). */
export function formatRelativeTime(value: string | Date, now: Date = new Date()): string {
  const seconds = (new Date(value).getTime() - now.getTime()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return RELATIVE.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function formatDateTime(value: string | Date): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(value: string | Date): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : pluralForm}`;
}
