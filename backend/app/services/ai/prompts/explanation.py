"""Module 8: explaining one deterministic diagnostic."""

from __future__ import annotations

from app.schemas.ai import DiagnosticInput
from app.services.ai.prompts.common import EVIDENCE_RULES

SYSTEM = f"""You explain compiler, type-checker, and linter diagnostics to the developer who is fixing \
them in CodeWalk's editor.

{EVIDENCE_RULES}

Explain the one diagnostic you are given:
- explanation: what the message means in plain words, and where in this code it applies.
- cause: the most likely cause in this code. If several causes are plausible, name them and say which \
the evidence favors.
- impact: what goes wrong if it is left as is (for example, the program fails to start, a value is \
wrong, or it is only a style issue).
- suggested_fix: how to fix it, in prose, with a short code fragment when that helps. Do not rewrite \
unrelated code.
- related_locations: other lines (in this file or in the supplied project context) that matter for the \
fix, each with a reason. Use only paths and lines that appear in the evidence.
- confidence: low, medium, or high."""


def user_message(
    diagnostic: DiagnosticInput, file_block: str, diagnostics_block: str, context_block: str
) -> str:
    target = (
        f"Diagnostic to explain: id={diagnostic.id} {diagnostic.severity.value} "
        f"[{diagnostic.source}{' ' + diagnostic.code if diagnostic.code else ''}] at line "
        f"{diagnostic.line}, column {diagnostic.column}: {diagnostic.message}"
    )
    parts = [target, file_block, diagnostics_block]
    if context_block:
        parts.append(context_block)
    return "\n\n".join(parts)
