import type { LanguageId } from "@/lib/languages";
import { BACKEND_LANGUAGES, type BackendLanguage } from "@/services/api/analysis";

const BACKEND = new Set<string>(BACKEND_LANGUAGES);

/**
 * The language to request from the analysis API. Without a manual override the
 * backend detects the language from the file path (its detection is authoritative).
 * Editor languages the backend does not know are sent as "plaintext" so the
 * override is respected rather than silently replaced by extension detection.
 */
export function analysisLanguageFor(
  path: string,
  override?: LanguageId,
): BackendLanguage | undefined {
  if (!override) return undefined;
  const lower = path.toLowerCase();
  if (override === "typescript") return lower.endsWith(".tsx") ? "typescriptreact" : "typescript";
  if (override === "javascript") return lower.endsWith(".jsx") ? "javascriptreact" : "javascript";
  return BACKEND.has(override) ? (override as BackendLanguage) : "plaintext";
}
