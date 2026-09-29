import pytest

from code_analysis.engine import UnsupportedLanguageError, analyze_code
from code_analysis.models import Severity


def test_analyze_code_with_explicit_language():
    result = analyze_code(source="x = 1\nprint(x)\n", language="python")
    assert result.language == "python"
    assert result.error_count == 0
    assert result.diagnostics == []


def test_analyze_code_detects_language_from_file_path():
    result = analyze_code(source="x = 1\n", file_path="script.py")
    assert result.language == "python"
    assert result.file_path == "script.py"


def test_analyze_code_syntax_error_counts():
    result = analyze_code(source="def f(:\n    pass\n", language="python")
    assert result.error_count == 1
    assert result.diagnostics[0].severity == Severity.ERROR


def test_analyze_code_empty_source_is_a_warning_not_a_crash():
    result = analyze_code(source="   \n", language="python")
    assert result.error_count == 0
    assert result.warning_count == 1
    assert result.diagnostics[0].code == "EmptySource"


def test_analyze_code_without_language_or_file_path_raises():
    with pytest.raises(UnsupportedLanguageError):
        analyze_code(source="x = 1")


def test_analyze_code_unknown_extension_raises():
    with pytest.raises(UnsupportedLanguageError):
        analyze_code(source="body { color: red; }", file_path="style.css")


def test_analyze_code_unsupported_explicit_language_raises():
    with pytest.raises(UnsupportedLanguageError):
        analyze_code(source="console.log('hi')", language="javascript")
