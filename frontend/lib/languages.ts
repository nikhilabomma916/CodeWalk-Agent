/**
 * Editor language registry and filename-based detection.
 *
 * `id` values are Monaco language ids. Detection here only chooses syntax
 * highlighting; authoritative analysis is performed by the backend.
 */

export interface LanguageDefinition {
  id: string;
  label: string;
}

export const LANGUAGES = [
  { id: "plaintext", label: "Plain Text" },
  { id: "javascript", label: "JavaScript" },
  { id: "typescript", label: "TypeScript" },
  { id: "python", label: "Python" },
  { id: "json", label: "JSON" },
  { id: "html", label: "HTML" },
  { id: "css", label: "CSS" },
  { id: "scss", label: "SCSS" },
  { id: "less", label: "Less" },
  { id: "java", label: "Java" },
  { id: "c", label: "C" },
  { id: "cpp", label: "C++" },
  { id: "csharp", label: "C#" },
  { id: "go", label: "Go" },
  { id: "rust", label: "Rust" },
  { id: "php", label: "PHP" },
  { id: "ruby", label: "Ruby" },
  { id: "kotlin", label: "Kotlin" },
  { id: "swift", label: "Swift" },
  { id: "sql", label: "SQL" },
  { id: "markdown", label: "Markdown" },
  { id: "yaml", label: "YAML" },
  { id: "xml", label: "XML" },
  { id: "shell", label: "Shell" },
  { id: "powershell", label: "PowerShell" },
  { id: "dockerfile", label: "Dockerfile" },
  { id: "ini", label: "INI / TOML" },
] as const satisfies readonly LanguageDefinition[];

export type LanguageId = (typeof LANGUAGES)[number]["id"];

const LANGUAGE_IDS: ReadonlySet<string> = new Set(LANGUAGES.map((language) => language.id));

export function isLanguageId(value: string): value is LanguageId {
  return LANGUAGE_IDS.has(value);
}

const EXTENSION_LANGUAGES: Readonly<Record<string, LanguageId>> = {
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  jsx: "javascript",
  ts: "typescript",
  mts: "typescript",
  cts: "typescript",
  tsx: "typescript",
  py: "python",
  pyi: "python",
  pyw: "python",
  json: "json",
  jsonc: "json",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  less: "less",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  hpp: "cpp",
  hh: "cpp",
  hxx: "cpp",
  cs: "csharp",
  go: "go",
  rs: "rust",
  php: "php",
  rb: "ruby",
  kt: "kotlin",
  kts: "kotlin",
  swift: "swift",
  sql: "sql",
  md: "markdown",
  markdown: "markdown",
  yml: "yaml",
  yaml: "yaml",
  xml: "xml",
  svg: "xml",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  ps1: "powershell",
  psm1: "powershell",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  txt: "plaintext",
};

const FILENAME_LANGUAGES: Readonly<Record<string, LanguageId>> = {
  dockerfile: "dockerfile",
  makefile: "shell",
  ".bashrc": "shell",
  ".zshrc": "shell",
  ".gitignore": "ini",
  ".editorconfig": "ini",
};

export function detectLanguage(filename: string): LanguageId {
  const base = filename.split(/[\\/]/).pop()?.toLowerCase() ?? "";
  const byName = FILENAME_LANGUAGES[base];
  if (byName) return byName;
  if (base.startsWith("dockerfile.")) return "dockerfile";

  const dot = base.lastIndexOf(".");
  if (dot <= 0 || dot === base.length - 1) return "plaintext";
  return EXTENSION_LANGUAGES[base.slice(dot + 1)] ?? "plaintext";
}

export function languageLabel(id: LanguageId): string {
  return LANGUAGES.find((language) => language.id === id)?.label ?? id;
}
