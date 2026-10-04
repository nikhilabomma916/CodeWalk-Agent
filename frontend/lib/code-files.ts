/**
 * Coding "+ New File": a file name only, with a programming/development extension. Mirrors the
 * backend (POST /projects/{id}/files/code-file), which enforces the same rules; this copy only gives
 * instant feedback.
 */
import { isSecretFile } from "@/lib/project-paths";

export const CODE_FILE_EXTENSIONS = [
  ".py",
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".java",
  ".c",
  ".h",
  ".cpp",
  ".cc",
  ".cxx",
  ".hpp",
  ".cs",
  ".go",
  ".rs",
  ".html",
  ".css",
  ".scss",
  ".sql",
  ".json",
  ".yaml",
  ".yml",
  ".md",
] as const;

export const MAX_CODE_FILE_NAME_LENGTH = 255;
export const UNSUPPORTED_FILE_TYPE =
  "Unsupported file type. CodeWalk Coding supports programming and development files.";

const FORBIDDEN = /[<>:"|?*]/;
const CONTROL = /[\u0000-\u001f\u007f]/;

/** An error message for an invalid file name, or null when it can be created. */
export function validateCodeFileName(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "Enter a file name, for example main.py.";
  if (name.length > MAX_CODE_FILE_NAME_LENGTH)
    return `File names can have at most ${MAX_CODE_FILE_NAME_LENGTH} characters.`;
  if (name.includes("/") || name.includes("\\")) return "Enter a file name only, without folders.";
  if (name === "." || name === ".." || CONTROL.test(name))
    return "The file name contains characters that are not allowed.";
  if (FORBIDDEN.test(name)) return 'File names cannot contain < > : " | ? *.';
  if (isSecretFile(name)) return "Credentials files such as .env are not created in Coding.";
  const dot = name.lastIndexOf(".");
  const extension = dot > 0 ? name.slice(dot).toLowerCase() : "";
  if (!(CODE_FILE_EXTENSIONS as readonly string[]).includes(extension))
    return UNSUPPORTED_FILE_TYPE;
  return null;
}
