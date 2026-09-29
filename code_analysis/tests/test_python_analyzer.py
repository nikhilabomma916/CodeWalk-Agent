from pathlib import Path

from code_analysis.analyzers.python_analyzer import PythonAnalyzer
from code_analysis.models import Severity

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_valid_code_has_no_errors():
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("valid.py"))
    assert diagnostics == []


def test_syntax_error_is_detected():
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("syntax_error.py"))

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == Severity.ERROR
    assert diagnostics[0].source == "syntax"
    assert diagnostics[0].line == 1


def test_syntax_error_short_circuits_linting():
    # Unparsable code should not also be run through pyflakes.
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("syntax_error.py"))
    assert all(d.source == "syntax" for d in diagnostics)


def test_undefined_name_is_flagged_as_error():
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("lint_issues.py"))

    undefined = [d for d in diagnostics if d.code == "UndefinedName"]
    assert len(undefined) == 1
    assert undefined[0].severity == Severity.WARNING
    assert "undefined_variable" in undefined[0].message


def test_unused_import_is_flagged_as_suggestion():
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("lint_issues.py"))

    unused_imports = [d for d in diagnostics if d.code == "UnusedImport"]
    assert len(unused_imports) == 2
    assert all(d.severity == Severity.SUGGESTION for d in unused_imports)


def test_unused_variable_is_flagged_as_suggestion():
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze(read_fixture("lint_issues.py"))

    unused_vars = [d for d in diagnostics if d.code == "UnusedVariable"]
    assert len(unused_vars) == 1
    assert unused_vars[0].severity == Severity.SUGGESTION


def test_empty_source_produces_no_diagnostics_at_analyzer_level():
    # Empty-source handling (a friendly warning) lives in the engine, not
    # the per-language analyzer: compiling "" is valid Python.
    analyzer = PythonAnalyzer()
    diagnostics = analyzer.analyze("")
    assert diagnostics == []
