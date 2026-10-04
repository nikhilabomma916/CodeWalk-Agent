# Developer experience (Module 17)

What a developer sees in the Coding workspace. Everything AI-generated is a proposal or advice: nothing
changes a file until the developer chooses to apply it.

## Agent panel (bottom panel → Agent)

- **Workflow selector**: Ask / fix, Code review, Generate tests, Write documentation, Refactor
  (multi-file), Impact analysis, Explain architecture. Suggestions change with the workflow.
- **Result** shows, in order: what was asked; the activity (tool calls as short status lines, never
  reasoning); **Context used** (the files the agent read, how many project notes it used, model calls
  and tokens); the answer; review findings; proposals; warnings (limits reached, fallbacks).
- **Review findings** are sorted by severity, labelled in text (CRITICAL … INFO, not color only), with
  the location (click to jump), explanation, evidence, suggestion, and confidence. **Propose fix**
  starts a separate request for a fix to that finding.
- **Proposals**:
  - single-file change: *Review diff* (side by side over the editor), *Apply*, *Reject*;
  - new file: labelled "new file", content shown inline, *Create file*;
  - multi-file change: one card listing every file with its diff, *Apply all N files* or *Reject all*;
    single files of a group cannot be applied alone.
  - Apply is disabled while the file has unsaved edits; a stale proposal is reported, not applied.

## Insights panel (bottom panel → Insights)

Works without an AI provider.

- **What could break?** For the open file, optionally one symbol: direct and indirect dependents
  (with the import chain), related tests and HTTP routes, and possible references, each labelled
  CONFIRMED or POSSIBLE; click a location to open it.
- **Architecture**: components with their file roles, imports between components, HTTP routes, entry
  points, and the analysis' limitations.
- **Project notes for the AI**: list, add (kind + text), and delete the notes the agent follows for this
  project. Notes that look like credentials are refused with an explanation.

## States

- AI unavailable: the agent panel says why (for example "AI assistance is turned off"); the editor,
  diagnostics, search, insights and notes keep working.
- Loading: every request shows a spinner with a status message (announced to screen readers).
- Errors: shown in place with the server's message; the request can be retried.
- Cancel: an agent request can be cancelled; the UI says the server may still finish it.

## Accessibility

Form controls have labels (workflow, symbol, note kind and text), lists and regions have names
(Review findings, Proposed changes, Files inspected, Impact analysis, Architecture, Project notes),
status and alerts use live regions, delete buttons name the note they delete, and severity and
relationship labels are text.
