from code_analysis.language_detect import detect_language, is_supported


def test_detects_python():
    assert detect_language("app.py") == "python"


def test_detects_typescript_react():
    assert detect_language("Login.tsx") == "typescript"


def test_unknown_extension_returns_none():
    assert detect_language("README.md") is None


def test_no_extension_returns_none():
    assert detect_language("Makefile") is None


def test_python_is_supported():
    assert is_supported("python") is True


def test_javascript_not_yet_supported():
    assert is_supported("javascript") is False
