"""Module 8: proposing a minimal fix as line-range edits (reviewed by the developer before use)."""

from __future__ import annotations

from app.schemas.ai import DiagnosticInput
from app.services.ai.prompts.common import EVIDENCE_RULES

SYSTEM = f"""You propose minimal code fixes in CodeWalk. The developer reviews your change as a diff \
and decides whether to apply it; nothing is applied automatically.

{EVIDENCE_RULES}

Propose the smallest change that fixes the stated problem in this file:
- Express it as edits. Each edit replaces the whole lines start_line..end_line (inclusive, using the \
line numbers shown) with `replacement`: the complete new text of those lines, without line numbers, \
with the file's existing indentation, joined by newline characters. To insert lines, replace an \
existing neighbouring line with itself plus the new lines. To delete lines, use an empty replacement.
- Edits must not overlap. Change only what the fix needs; keep everything else byte-for-byte the same.
- If the fix needs changes in other files, or you cannot propose a safe change from the evidence, \
return no edits and explain why in no_change_reason (otherwise set it to null).
- summary: one sentence describing the change. explanation: why it fixes the problem and anything the \
developer should check."""


def user_message(
    diagnostic: DiagnosticInput | None,
    instruction: str | None,
    file_block: str,
    diagnostics_block: str,
    context_block: str,
) -> str:
    parts: list[str] = []
    if diagnostic is not None:
        parts.append(
            f"Problem to fix: id={diagnostic.id} {diagnostic.severity.value} "
            f"[{diagnostic.source}{' ' + diagnostic.code if diagnostic.code else ''}] at line "
            f"{diagnostic.line}, column {diagnostic.column}: {diagnostic.message}"
        )
    if instruction:
        parts.append(f"Developer's request: {instruction.strip()}")
    parts += [file_block, diagnostics_block]
    if context_block:
        parts.append(context_block)
    return "\n\n".join(parts)
