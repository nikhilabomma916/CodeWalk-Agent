// CodeWalk TypeScript/JavaScript analyzer worker.
//
// Protocol: one JSON request per line on stdin, one JSON response per line on stdout.
//   request:  {"id": 1, "fileName": "input.tsx", "text": "..."}
//   response: {"id": 1, "ok": true, "diagnostics": [...]} | {"id": 1, "ok": false, "error": "..."}
//
// The analyzed text is only parsed and type-checked by the TypeScript compiler; it
// is never executed. Imports are not resolved (noResolve) and the compiler host can
// read nothing from disk except TypeScript's own lib.*.d.ts files.
import path from "node:path";
import readline from "node:readline";

import ts from "typescript";

const VIRTUAL_DIR = path.posix.join("/", "__codewalk__");

const tsOptions = {
  target: ts.ScriptTarget.ESNext,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  jsx: ts.JsxEmit.Preserve,
  allowJs: true,
  checkJs: false,
  strict: true,
  noImplicitAny: false,
  noResolve: true,
  noEmit: true,
  skipLibCheck: true,
  esModuleInterop: true,
  allowNonTsExtensions: true,
};

// Plain JavaScript is checked with checkJs, but only diagnostics that are
// unambiguous without type information are kept (see JS_SEMANTIC_CODES).
const jsOptions = { ...tsOptions, checkJs: true };

const libDir = path.dirname(ts.getDefaultLibFilePath(tsOptions));
const normalize = (fileName) => fileName.replace(/\\/g, "/");
const isLibFile = (fileName) => normalize(path.resolve(fileName)).startsWith(normalize(libDir) + "/");

// Diagnostics that only mean "the rest of the project is not loaded".
const IGNORED_CODES = new Set([
  2307, // Cannot find module
  2792, // Cannot find module (did you mean to set moduleResolution)
  7016, // Could not find a declaration file for module
  2580, 2582, 2591, 2593, // Cannot find name 'require'/'describe'/... (missing @types)
  2503, // Cannot find namespace
  2688, // Cannot find type definition file
  2875, // JSX runtime module not found
]);
const JS_SEMANTIC_CODES = new Set([
  2300, // Duplicate identifier
  2451, // Cannot redeclare block-scoped variable
  2588, // Cannot assign to a constant
  2630, // Cannot assign to a function
  2632, // Cannot assign to an import
  7027, // Unreachable code
  7028, // Unused label
]);
// Reported as warnings: without the project's ambient declarations, some globals are unknown.
const DOWNGRADED_CODES = new Set([2304]);

let current = { fileName: "", text: "", version: 0 };
const libCache = new Map();

function createService(options) {
  const host = {
  getScriptFileNames: () => (current.fileName ? [current.fileName] : []),
  getScriptVersion: (fileName) => (fileName === current.fileName ? String(current.version) : "1"),
  getScriptSnapshot(fileName) {
    if (fileName === current.fileName) return ts.ScriptSnapshot.fromString(current.text);
    if (!isLibFile(fileName)) return undefined;
    if (!libCache.has(fileName)) {
      const text = ts.sys.readFile(fileName);
      if (text === undefined) return undefined;
      libCache.set(fileName, ts.ScriptSnapshot.fromString(text));
    }
    return libCache.get(fileName);
  },
  getCurrentDirectory: () => VIRTUAL_DIR,
  getCompilationSettings: () => options,
  getDefaultLibFileName: (opts) => ts.getDefaultLibFilePath(opts),
  fileExists: (fileName) => fileName === current.fileName || (isLibFile(fileName) && ts.sys.fileExists(fileName)),
  readFile: (fileName) =>
    fileName === current.fileName ? current.text : isLibFile(fileName) ? ts.sys.readFile(fileName) : undefined,
  directoryExists: (dir) => normalize(dir) === VIRTUAL_DIR || isLibFile(path.join(dir, "x")),
  getDirectories: () => [],
};

  return ts.createLanguageService(host, registry);
}

const registry = ts.createDocumentRegistry();
const tsService = createService(tsOptions);
const jsService = createService(jsOptions);
const isJavaScript = (fileName) => /.(c|m)?jsx?$/i.test(fileName);

function position(file, offset) {
  const { line, character } = file.getLineAndCharacterOfPosition(offset);
  return { line: line + 1, column: character + 1 };
}

function convert(file, diagnostic, category) {
  const start = diagnostic.start ?? 0;
  const end = start + (diagnostic.length ?? 0);
  let severity =
    diagnostic.category === ts.DiagnosticCategory.Error
      ? "error"
      : diagnostic.category === ts.DiagnosticCategory.Warning
        ? "warning"
        : "information";
  if (category === "suggestion") severity = diagnostic.reportsDeprecated ? "information" : "warning";
  if (DOWNGRADED_CODES.has(diagnostic.code)) severity = "warning";
  return {
    code: diagnostic.code,
    category,
    severity,
    message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
    start: position(file, start),
    end: position(file, end),
    unnecessary: Boolean(diagnostic.reportsUnnecessary),
    deprecated: Boolean(diagnostic.reportsDeprecated),
  };
}

function analyze({ fileName, text }) {
  current = { fileName: path.posix.join(VIRTUAL_DIR, path.posix.basename(fileName)), text, version: current.version + 1 };
  const javascript = isJavaScript(current.fileName);
  const service = javascript ? jsService : tsService;
  const program = service.getProgram();
  const file = program?.getSourceFile(current.fileName);
  if (!file) throw new Error("TypeScript could not load the source");

  const syntactic = service.getSyntacticDiagnostics(current.fileName);
  const results = syntactic.map((d) => convert(file, d, "syntax"));
  // Semantic checks on syntactically broken code mostly repeat the syntax errors.
  if (syntactic.length === 0) {
    for (const d of service.getSemanticDiagnostics(current.fileName)) {
      if (IGNORED_CODES.has(d.code)) continue;
      if (javascript && !(d.code < 2000 || JS_SEMANTIC_CODES.has(d.code))) continue;
      results.push(convert(file, d, javascript ? "semantic" : "type"));
    }
    for (const d of service.getSuggestionDiagnostics(current.fileName)) {
      if (d.reportsUnnecessary || d.reportsDeprecated) results.push(convert(file, d, "suggestion"));
    }
  }
  return results;
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    return;
  }
  let response;
  try {
    if (request.ping) response = { id: request.id, ok: true, version: ts.version };
    else response = { id: request.id, ok: true, diagnostics: analyze(request) };
  } catch (error) {
    response = { id: request.id, ok: false, error: String(error?.message ?? error) };
  }
  process.stdout.write(JSON.stringify(response) + "\n");
});
input.on("close", () => process.exit(0));
