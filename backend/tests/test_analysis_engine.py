"""Analyzer behavior per language, through the real engine."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services.analysis.engine import AnalysisEngine, SourceTooLargeError
from app.services.analysis.models import AnalysisResult, CapabilityKind, CapabilityStatus, Severity
from app.services.analysis.typescript_worker import TypeScriptWorker
from app.services.languages import Language


@pytest.fixture(scope="module")
def worker() -> Iterator[TypeScriptWorker]:
    worker = TypeScriptWorker()
    yield worker
    worker.close()


@pytest.fixture(scope="module")
def engine(worker: TypeScriptWorker) -> AnalysisEngine:
    return AnalysisEngine.create_default(
        max_source_bytes=200_000, timeout_seconds=20, typescript_worker=worker
    )


@pytest.fixture
def typescript_available(worker: TypeScriptWorker) -> None:
    reason = worker.unavailable_reason()
    if reason:
        pytest.skip(f"TypeScript analyzer unavailable: {reason}")


def codes(result: AnalysisResult) -> set[str | None]:
    return {d.code for d in result.diagnostics}


def capability(result: AnalysisResult, kind: CapabilityKind) -> CapabilityStatus:
    return next(c.status for c in result.capabilities if c.kind is kind)


# --- Python -------------------------------------------------------------------


def test_valid_python_has_no_diagnostics(engine: AnalysisEngine) -> None:
    result = engine.analyze("def add(a: int, b: int) -> int:\n    return a + b\n", file_path="calc.py")
    assert result.success
    assert result.language is Language.PYTHON
    assert result.diagnostics == []
    assert capability(result, CapabilityKind.SYNTAX) is CapabilityStatus.PERFORMED
    assert capability(result, CapabilityKind.LINT) is CapabilityStatus.PERFORMED
    assert capability(result, CapabilityKind.TYPES) is CapabilityStatus.NOT_SUPPORTED


def test_python_syntax_error_location(engine: AnalysisEngine) -> None:
    result = engine.analyze("def broken(:\n    pass\n", file_path="bad.py")
    [diagnostic] = result.diagnostics
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.category.value == "syntax"
    assert diagnostic.source == "python"
    assert (diagnostic.line, diagnostic.column) == (1, 12)
    # Linting is skipped rather than run on unparsable code.
    assert capability(result, CapabilityKind.LINT) is CapabilityStatus.SKIPPED


def test_python_indentation_error(engine: AnalysisEngine) -> None:
    result = engine.analyze("def f():\nreturn 1\n", file_path="indent.py")
    [diagnostic] = result.diagnostics
    assert diagnostic.code == "IndentationError"
    assert diagnostic.line == 2


def test_python_multiple_lint_diagnostics(engine: AnalysisEngine) -> None:
    source = "import os\nimport sys\n\n\ndef f():\n    value = 1\n    return undefined_name\n"
    result = engine.analyze(source, file_path="lint.py")
    assert {"F401", "F841", "F821"} <= codes(result)
    by_code = {d.code: d for d in result.diagnostics}
    assert by_code["F821"].severity is Severity.ERROR  # would fail at runtime
    assert by_code["F401"].severity is Severity.WARNING
    assert by_code["F401"].fixable
    assert by_code["F401"].documentation_url
    assert sorted(d.line for d in result.diagnostics if d.code == "F401") == [1, 2]


def test_empty_python_file(engine: AnalysisEngine) -> None:
    result = engine.analyze("", file_path="empty.py")
    assert result.success
    assert result.diagnostics == []


def test_python_code_is_not_executed(engine: AnalysisEngine, tmp_path: object) -> None:
    marker = "codewalk_executed_marker"
    source = f"import builtins\nbuiltins.{marker} = True\nraise SystemExit(1)\n"
    engine.analyze(source, file_path="evil.py")
    import builtins

    assert not hasattr(builtins, marker)


# --- JSON ---------------------------------------------------------------------


def test_valid_json(engine: AnalysisEngine) -> None:
    result = engine.analyze('{"name": "codewalk", "tags": [1, 2, 3]}', file_path="package.json")
    assert result.diagnostics == []


@pytest.mark.parametrize(
    ("source", "line", "column"),
    [
        ('{"a": 1,}', 1, 9),  # trailing comma
        ('{\n  "a": [1, 2\n}', 3, 1),  # unclosed array
        ("{\"a\": 'x'}", 1, 7),  # single-quoted string
        ('{"a": tru}', 1, 7),  # invalid literal
    ],
)
def test_invalid_json_positions(engine: AnalysisEngine, source: str, line: int, column: int) -> None:
    [diagnostic] = engine.analyze(source, file_path="data.json").diagnostics
    assert diagnostic.severity is Severity.ERROR
    assert (diagnostic.line, diagnostic.column) == (line, column)


def test_json_duplicate_keys_warn(engine: AnalysisEngine) -> None:
    [diagnostic] = engine.analyze('{"a": 1,\n "a": 2}', file_path="data.json").diagnostics
    assert diagnostic.code == "duplicate-key"
    assert diagnostic.line == 2


def test_jsonc_allows_comments_and_trailing_commas(engine: AnalysisEngine) -> None:
    source = '{\n  // comment\n  "compilerOptions": {"strict": true, /* x */},\n}\n'
    assert engine.analyze(source, file_path="tsconfig.json").diagnostics == []
    assert engine.analyze(source, file_path="data.json").diagnostics  # strict JSON rejects it


# --- JavaScript / TypeScript ----------------------------------------------------


@pytest.mark.usefixtures("typescript_available")
def test_valid_typescript(engine: AnalysisEngine) -> None:
    result = engine.analyze(
        "export function add(a: number, b: number): number {\n  return a + b;\n}\n", file_path="add.ts"
    )
    assert result.success, result.errors
    assert result.diagnostics == []
    assert capability(result, CapabilityKind.TYPES) is CapabilityStatus.PERFORMED


@pytest.mark.usefixtures("typescript_available")
def test_typescript_syntax_error(engine: AnalysisEngine) -> None:
    result = engine.analyze("const total = (1 + ;\n", file_path="bad.ts")
    [diagnostic] = result.diagnostics
    assert diagnostic.code == "TS1109"
    assert diagnostic.category.value == "syntax"
    assert (diagnostic.line, diagnostic.column) == (1, 20)


@pytest.mark.usefixtures("typescript_available")
def test_typescript_type_error(engine: AnalysisEngine) -> None:
    result = engine.analyze('export const count: number = "three";\n', file_path="types.ts")
    assert "TS2322" in codes(result)


@pytest.mark.usefixtures("typescript_available")
def test_typescript_unresolved_imports_are_not_reported(engine: AnalysisEngine) -> None:
    result = engine.analyze(
        'import { thing } from "./elsewhere";\nexport const x = thing;\n', file_path="a.ts"
    )
    assert "TS2307" not in codes(result)


@pytest.mark.usefixtures("typescript_available")
def test_tsx_is_supported(engine: AnalysisEngine) -> None:
    result = engine.analyze('export const App = () => <div className="x">hi</div>;\n', file_path="App.tsx")
    assert result.language is Language.TYPESCRIPT_REACT
    assert result.diagnostics == []


@pytest.mark.usefixtures("typescript_available")
def test_javascript_valid_and_invalid(engine: AnalysisEngine) -> None:
    assert engine.analyze("export const double = (n) => n * 2;\n", file_path="a.js").diagnostics == []
    broken = engine.analyze("function f( {\n", file_path="b.js")
    assert broken.diagnostics
    assert broken.diagnostics[0].category.value == "syntax"


@pytest.mark.usefixtures("typescript_available")
def test_javascript_semantic_checks_without_type_noise(engine: AnalysisEngine) -> None:
    source = "const limit = 1;\nlimit = 2;\nconst o = {};\no.dynamic = 5;\nexport { o };\n"
    result = engine.analyze(source, file_path="c.js")
    assert "TS2588" in codes(result)  # assignment to a constant
    assert "TS2339" not in codes(result)  # dynamic property: not flagged in JavaScript
    assert capability(result, CapabilityKind.TYPES) is CapabilityStatus.NOT_SUPPORTED


# --- Other languages ------------------------------------------------------------


def test_html_structure(engine: AnalysisEngine) -> None:
    result = engine.analyze("<div><span>text</div>\n<p id=a></p><p id=a></p></br>", file_path="index.html")
    assert {"unclosed-element", "duplicate-id", "void-end-tag"} <= codes(result)
    assert (
        engine.analyze("<!doctype html><ul><li>a<li>b</ul><img src=x>", file_path="ok.html").diagnostics == []
    )


def test_css_syntax(engine: AnalysisEngine) -> None:
    assert engine.analyze("a { color: red; }\n", file_path="site.css").diagnostics == []
    assert engine.analyze("a { color: red;\n", file_path="site.css").diagnostics


def test_sql_syntax(engine: AnalysisEngine) -> None:
    assert engine.analyze("SELECT id, name FROM users WHERE id = 1;", file_path="q.sql").diagnostics == []
    [diagnostic] = engine.analyze("SELECT id FROM users WHERE", file_path="q.sql").diagnostics
    assert diagnostic.severity is Severity.WARNING  # dialect-dependent, so never an error
    assert "WHERE" in diagnostic.message


def test_markdown_rules(engine: AnalysisEngine) -> None:
    result = engine.analyze("# Title\n### Skipped\n#NoSpace\n```\ncode\n", file_path="README.md")
    assert {"MD001", "MD018", "unclosed-fence"} <= codes(result)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("Main.java", "class A { void f() { int x = ; } }"),
        ("main.c", "int main() { return 0 }"),
        ("main.cpp", "int main() { auto x = ; }"),
    ],
)
def test_tree_sitter_syntax_errors(engine: AnalysisEngine, path: str, source: str) -> None:
    result = engine.analyze(source, file_path=path)
    assert result.diagnostics
    assert all(d.category.value == "syntax" for d in result.diagnostics)
    assert capability(result, CapabilityKind.TYPES) is CapabilityStatus.NOT_SUPPORTED


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("Main.java", "class A { int f() { return 1; } }"),
        ("main.c", "int main(void) { return 0; }"),
        ("main.cpp", "#include <vector>\nint main() { std::vector<int> v{1}; return v.size(); }"),
    ],
)
def test_tree_sitter_valid_sources(engine: AnalysisEngine, path: str, source: str) -> None:
    assert engine.analyze(source, file_path=path).diagnostics == []


# --- Engine behavior ------------------------------------------------------------


def test_unsupported_language_is_reported_honestly(engine: AnalysisEngine) -> None:
    result = engine.analyze("key: value\n", file_path="config.yaml")
    assert result.success
    assert result.language is Language.YAML
    assert result.diagnostics == []
    assert {c.status for c in result.capabilities} == {CapabilityStatus.NOT_SUPPORTED}


def test_explicit_language_overrides_extension(engine: AnalysisEngine) -> None:
    result = engine.analyze("{bad json", language=Language.JSON, file_path="notes.txt")
    assert result.language is Language.JSON
    assert result.diagnostics


def test_oversized_source_is_rejected(engine: AnalysisEngine) -> None:
    with pytest.raises(SourceTooLargeError):
        engine.analyze("x" * 200_001, file_path="big.py")


def test_crashing_analyzer_is_isolated(engine: AnalysisEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    [json_analyzer] = engine.registry.for_language(Language.JSON)

    def explode(_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(json_analyzer, "analyze", explode)
    result = engine.analyze("{}", file_path="a.json")
    assert not result.success
    assert result.errors == ["The json analyzer failed on this input"]


def test_large_valid_python_within_limits(engine: AnalysisEngine) -> None:
    source = "".join(f"def f{i}(x):\n    return x + {i}\n\n\n" for i in range(2000))
    result = engine.analyze(source, file_path="big.py")
    assert result.success
    assert result.diagnostics == []
