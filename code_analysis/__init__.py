"""Code Analysis Engine for CodeWalk Agent.

Public entry point:

    from code_analysis import analyze_code

    result = analyze_code(source="print('hi'", language="python")
    result.diagnostics  # list[Diagnostic]
"""

from code_analysis.engine import UnsupportedLanguageError, analyze_code
from code_analysis.models import AnalysisResult, Diagnostic, Severity

__all__ = [
    "analyze_code",
    "AnalysisResult",
    "Diagnostic",
    "Severity",
    "UnsupportedLanguageError",
]
