# Developer experience (Module 17)

What a developer sees in the Coding workspace. Everything AI-generated is a proposal or advice: nothing
changes a file until the developer chooses to apply it.

## Upload a folder from your computer (Module 18)

**Upload folder** (Coding start screen, or the header icon) copies a local folder into a new server
project, so search, project intelligence, Insights, and the agent can work on it. "Open local folder"
still edits a folder in place in the browser, but those server features need an uploaded project.

- Pick a folder; the dialog shows how many files will be uploaded and which are skipped before
  anything is sent: dependency and build folders (node_modules, .git, …), `.env` and other credential
  files, binary files, and files over 2 MB. The project name defaults to the folder name.
- Files are sent in batches (`POST /projects/{id}/files/import`, at most 100 files and about 4 MB per
  request) with a progress bar; **Cancel upload** stops between batches and keeps what was uploaded.
- The server checks every file again (unsafe paths, credentials, ignored folders, size, the project
  file limit) and never overwrites an existing file; skipped files are listed with the reason.
- **Open project** opens it in the workspace and analyzes it (files, symbols, imports). Code is
  analyzed, never executed.

## New code files (Coding → Explorer → New File)

**New File** asks only for a file name (for example `main.py`); the file is created at the project root
and opens in the editor with diagnostics. There is no folder step. Allowed: .py .js .jsx .ts .tsx .java
.c .h .cpp .cc .cxx .hpp .cs .go .rs .html .css .scss .sql .json .yaml .yml .md. Folders, `..`,
absolute paths, control characters, credential files, and binary/media types are rejected (by the
browser for quick feedback and by the server, `POST /projects/{id}/files/code-file`). An existing file
is never overwritten: the dialog offers **Open existing file**. Existing folder structures are kept.

## Project page

The project page leads with **Ask about this project** (the agent answers only what was asked; cited
files open in Coding; proposed changes are reviewed in Coding). Statistics, files, languages, and
details are behind **Show project details**.

## Light and dark themes

The theme switch is in the navigation rail and on the sign-in pages. The choice is saved in this
browser only (or follows the system setting); the editor switches with it without losing its state.

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
