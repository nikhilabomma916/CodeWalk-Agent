// Copies Monaco's AMD build into public/ so the editor is served by this app
// (same version as package.json, no third-party CDN at runtime).
import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), "..");
// monaco-editor's "exports" map does not expose package.json, so locate it directly.
const monacoDir = join(frontendDir, "node_modules", "monaco-editor");
const { version } = JSON.parse(readFileSync(join(monacoDir, "package.json"), "utf8"));

const source = join(monacoDir, "min", "vs");
const target = join(frontendDir, "public", "monaco", "vs");
const stamp = join(frontendDir, "public", "monaco", ".version");

if (!existsSync(source)) {
  console.error(`[copy-monaco] ${source} not found; is monaco-editor installed?`);
  process.exit(1);
}

if (existsSync(stamp) && readFileSync(stamp, "utf8") === version && existsSync(target)) {
  process.exit(0);
}

rmSync(target, { recursive: true, force: true });
cpSync(source, target, { recursive: true });
writeFileSync(stamp, version);
console.log(`[copy-monaco] copied monaco-editor ${version} to public/monaco/vs`);
