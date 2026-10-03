"""Module 7: AI code review on top of deterministic diagnostics."""

from __future__ import annotations

from app.schemas.ai import AIAnalysisType, SourceRange
from app.services.ai.prompts.common import EVIDENCE_RULES

FOCUS = {
    AIAnalysisType.GENERAL_REVIEW: (
        "Review the file for likely bugs, logic errors, maintainability problems, code smells, "
        "unnecessary complexity, duplicated logic, and performance concerns."
    ),
    AIAnalysisType.BUG_DETECTION: "Look for likely bugs: logic errors, wrong conditions, unhandled cases, "
    "misuse of APIs, off-by-one errors, and incorrect error handling.",
    AIAnalysisType.QUALITY_REVIEW: "Assess maintainability: naming, structure, duplication, complexity, and "
    "architecture. Prefer a few well-justified observations over many small ones.",
    AIAnalysisType.SECURITY_REVIEW: "Look for security-sensitive patterns supported by the code itself, "
    "such as injection, unsafe deserialization, path traversal, hard-coded secrets, or missing validation of "
    "untrusted input. Report nothing when there is no such evidence.",
    AIAnalysisType.PERFORMANCE_REVIEW: "Look for performance concerns visible in the code: repeated work, "
    "inefficient data structures or queries, unbounded growth, and blocking calls in hot paths.",
    AIAnalysisType.EXPLAIN_CODE: "Explain what the code does: its purpose, main control flow, and important "
    "assumptions. Use findings with category 'explanation' and severity 'info' for each part you explain.",
}

SYSTEM = f"""You are the code-review component of CodeWalk, a developer tool. Your findings are shown \
next to deterministic compiler/linter diagnostics in the developer's editor, as advisory input they \
will verify themselves.

{EVIDENCE_RULES}

The deterministic diagnostics are already shown to the developer. Do not repeat them as findings. \
Mention one only when you add something it does not say (for example, its root cause or a related \
problem), and then set related_diagnostic_id to its id.

For each finding give: a short title; a description of the problem; your reasoning; the exact code it \
concerns as evidence (copied from the file); the line range; a confidence of low, medium, or high; and a \
concrete suggestion when there is one. Return an empty findings list when there is nothing worth \
reporting; that is a valid answer. The summary is two or three sentences about the file overall."""


def user_message(
    analysis_type: AIAnalysisType,
    file_block: str,
    diagnostics_block: str,
    context_block: str,
    selected_range: SourceRange | None,
) -> str:
    focus = FOCUS[analysis_type]
    if selected_range is not None:
        focus += (
            f" Focus on lines {selected_range.start_line}-{selected_range.end_line}; use the rest of the "
            "file only as context."
        )
    parts = [f"Task: {focus}", file_block, diagnostics_block]
    if context_block:
        parts.append(context_block)
    return "\n\n".join(parts)
