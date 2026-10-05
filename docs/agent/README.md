# Agent workflows (Module 17)

The agent is a bounded, policy-checked tool loop (Module 11). Module 17 adds **workflows**, new
**read-only tools** for multi-file reasoning, **review findings**, **multi-file and new-file
proposals**, and **budgets**. What the agent may do has not widened: it reads the signed-in user's own
project through tools, and it can only *store proposals*. Applying anything still requires the
developer's explicit approval, re-validated at decision time.

## Workflows (`mode`)

`POST /api/v1/agent/run` takes `mode` (default `assist`). The mode adds fixed guidance to the
system prompt (written by CodeWalk, never taken from the project); permissions and limits are the
same for every mode.

| Mode | What the agent is told to do | Typical tools |
| --- | --- | --- |
| `assist` | Explain, find, or (when asked) propose a minimal fix | search, get_file_content, explain_error, propose_fix |
| `review` | Review the open file/selection and the code it depends on; record one finding per real issue; propose nothing unless asked | get_file_content, analyze_impact, record_finding |
| `tests` | Read existing tests first (framework, fixtures, naming), then propose a new test file or extend one | find_related_tests, get_file_content, propose_new_file / propose_fix |
| `docs` | Document only behavior visible in code read; say when something cannot be determined | get_file_content, propose_fix, propose_new_file |
| `refactor` | Run impact analysis, read affected files, submit **one** multi-file proposal | analyze_impact, find_references, propose_changes |
| `impact` | Explain what may break; separate confirmed from possible relationships | analyze_impact, find_related_tests |
| `architecture` | Explain how the project is built, with file paths | get_architecture, get_file_content |

## Tools

17 tools; the model can call only `read_only` and `proposed_change` tools (WRITE is never in its
permission set; `test_tools_have_permissions_and_no_write_tools` pins the full inventory).

New in Module 17:

| Tool | Permission | Notes |
| --- | --- | --- |
| `get_architecture` | read_only | Deterministic summary (see insights below) |
| `get_project_activity` | read_only | Recent activity of this project for this user only (file saves, analyses, AI and agent use), newest first, bounded (≤ 40 events, trimmed details); for "what have we done / what changed" questions |
| `analyze_impact` | read_only | Dependents through resolved imports (**confirmed**), same-name mentions (**possible**), related tests and HTTP routes |
| `find_references` | read_only | Definitions and referencing files, labelled confirmed/possible |
| `find_related_tests` | read_only | Test files importing a file (confirmed) or named after it (possible) |
| `record_finding` | read_only | Adds a finding to the run report; changes no file (see review) |
| `propose_changes` | proposed_change | One coordinated change across up to 10 saved files |
| `propose_new_file` | proposed_change | A new file (tests, docs); refused for existing, ignored, or credential paths |

## Multi-file reasoning

The agent reads only what it needs, one tool call per step: impact analysis and references find the
related files (callers through imports, tests, routes); `get_file_content` reads bounded ranges
(200 lines per call); repeated identical calls are denied, so context is not duplicated. Every run
records the files actually read (`context.files_inspected`), shown in the UI as "Context used". The
policy requires the answer to name the files inspected, the evidence (file:line), the conclusion, and
the confidence, and to present "possible" relationships as possible. No reasoning is requested or
stored: progress events are short status lines.

## Code review

`record_finding` validates each finding before it is stored: the file must be a project file the
agent can read, the line range must be inside it, and severity (`info` … `critical`), category
(correctness, bug, security, performance, maintainability, architecture, error_handling, concurrency,
testing, accessibility, api_contract, database) and confidence (`low`/`medium`/`high`) come from fixed
sets. Evidence is required. At most 20 findings per run. The stored finding includes the exact project
lines it points at (`excerpt`), so the UI shows real code, not the model's paraphrase.

**Finding → fix:** "Propose fix" in the UI starts a new, separate `assist` run asking for a minimal
fix for that finding; the result is an ordinary proposal reviewed and approved like any other.

## Proposals

| Field | Meaning |
| --- | --- |
| `kind` | `code_change` (edit an existing file) or `create_file` |
| `group_id`, `group_size` | Proposals from one tool call; a group of more than one is decided as a whole |
| `summary`, `explanation` | Title and reason |
| `changes` | Exact ranges with original and replacement text |
| `diff` | Unified diff for review |
| `confidence`, `risk` | Stated by the model (`low`/`medium`/`high`), shown to the developer |
| `status` | `pending` → `applied` / `rejected` / `stale` |

Status mapping to the module specification: `pending` is READY_FOR_REVIEW; approval and application
are one step (`applied`); `rejected`; `stale` (the file changed, or a group member did). A proposal that
fails validation is never stored (the tool call fails: there is no FAILED proposal), and there is no
DRAFT state because the agent never edits a proposal after creating it.

**Approval** (`POST /agent/actions/{id}/approve` for a single proposal,
`POST /agent/groups/{group_id}/approve` for a group):

1. the actions belong to the user and are pending (rows locked);
2. the project is the user's and writable;
3. every file row is locked (in a fixed order, so groups cannot deadlock), exists at the same path,
   and still has exactly the content the proposal was computed against; every original range still
   holds its original text; new-file paths are still free and allowed;
4. if **any** file fails, **nothing** is applied and the whole group becomes `stale`;
5. otherwise every file is saved in **one transaction**: new version, deterministic re-analysis,
   history entries; the response returns each saved file and its diagnostics count.

Deciding a single member of a multi-file group is refused (`409 group_decision_required`).
Tests generated by the agent are **never executed** by CodeWalk (it never runs project code); the
developer runs them.

## Budgets and cost controls

| Setting | Default | Effect |
| --- | --- | --- |
| `CODEWALK_AGENT_MAX_STEPS` | 8 | Model turns per run |
| `CODEWALK_AGENT_MAX_TOOL_CALLS` | 12 | Tool calls per run (new) |
| `CODEWALK_AGENT_MAX_TOKENS_PER_RUN` | 400,000 | Provider tokens (input + output) before the run must answer (new) |
| `CODEWALK_AGENT_MAX_CONTEXT_CHARS` | 60,000 | Tool output kept in the prompt |
| `CODEWALK_AGENT_MAX_ACTIONS` | 3 | Proposal tool calls per run (a multi-file proposal counts once) |
| `CODEWALK_AGENT_TIMEOUT_SECONDS` | 240 | Whole run |
| `CODEWALK_AGENT_MAX_RUNS` | 20 / 10 min | Runs per user (atomic limiter) |

Each run stores `usage`: provider calls, input and output tokens (as reported by the provider), tool
calls, and the largest prompt size. Reaching a limit ends the run as `limit_reached` with a warning
naming the limit.

## Focused answers

Policy rule 8 tells the agent to answer the developer's actual question and nothing more: it fetches
only the context the question needs (the open file and selection for a line or function, activity for
"what have we done", architecture for architecture questions), does not volunteer unrelated project
information, answers general coding questions without tools, and cites file:line only when the answer
rests on project code. Tests check that a general question sends no project files and that history
comes only from the user's own project.
