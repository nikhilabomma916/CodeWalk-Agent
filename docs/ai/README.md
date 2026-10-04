# Advanced AI architecture (Module 17)

How CodeWalk's AI features fit together, how providers are isolated, how project data is kept from
acting as instructions, and what is deliberately not implemented. Agent workflows and proposals are in
[../agent/README.md](../agent/README.md); the user-facing features in
[../developer-experience/README.md](../developer-experience/README.md).

```text
Developer request ─► AgentService (ownership, limits, mode)
                      ├─ prompts: SYSTEM = policy + tools + mode guidance (CodeWalk text only)
                      │           USER   = <developer_request> + <developer_notes> + <editor>
                      │                    + <project_data> tool results (escaped)
                      ├─ AIService.run ─► AIProvider (anthropic | openai) ─► validated JSON step
                      ├─ ToolPolicy (permission, repeats, tool-call / proposal budgets)
                      └─ tools ─► ProjectSearchService / insights / context (one user's project)
                                  └─ proposals stored; applied only by explicit approval
```

## Deterministic first

Project understanding that does not need a model is computed deterministically and works without a
provider: symbols, imports and their resolution (Module 5), search and context (Modules 9-10), and
Module 16's incremental project index. Module 17 adds `app/services/insights.py`:

- **Architecture**: components (top folders), file roles (test, config, docs, api_route, data_model,
  schema, service, repository, frontend component/page/API client, …) with the reason for each, import
  links between components, entry points, HTTP routes (`@router.get(...)`-style decorators), database
  models (`__tablename__` / `Mapped[...]`).
- **Impact**: direct dependents (resolved imports; for a symbol, files that import or mention it),
  indirect dependents (import chains, depth 3, with the chain), same-file references, possible
  references (the name occurs but no import connects the file), related tests, related HTTP routes.
- **References** and **related tests**.

Every relationship is **confirmed** (a resolved import, or use inside the defining file) or
**possible** (name only). There is no call graph and no type analysis; the reports say so in
`limitations`. Endpoints: `GET /projects/{id}/architecture`, `POST /projects/{id}/impact`,
`POST /projects/{id}/references` (owner only; 404 otherwise).

## Provider abstraction

`app/services/ai/base.py` defines the `AIProvider` protocol:

| Method | Purpose |
| --- | --- |
| `status()` | Health/configuration without a network call |
| `generate_structured(request)` | One request whose answer must match a JSON schema; raises `AIError` subclasses only |

Providers are registered in `app/services/ai/providers/__init__.py` and selected with
`CODEWALK_AI_PROVIDER`:

| Provider | Status | Credential |
| --- | --- | --- |
| `anthropic` (default) | Supported (Modules 7-11) | `CODEWALK_AI_API_KEY` or `ANTHROPIC_API_KEY` |
| `openai` | **Experimental** (Module 17): Chat Completions with a JSON-schema response format; also serves compatible servers via `CODEWALK_AI_BASE_URL` (https only; http for localhost) | `CODEWALK_AI_API_KEY` or `OPENAI_API_KEY`; `CODEWALK_AI_MODEL` is required (no model is assumed) |

The credential is taken only from `CODEWALK_AI_API_KEY` or the *selected* provider's own variable, so
one provider's key is never sent to another. The OpenAI-compatible provider is tested against a mock
transport only; no live call has been made (no credential). With no provider configured, AI features
report "unavailable" and every deterministic feature keeps working.

## Prompt-injection defense

All project content is untrusted data:

1. The **system prompt** contains only CodeWalk's policy, the tool catalog, and fixed mode guidance.
   Nothing from the project, the request, or memory is ever placed in it (tests assert it is identical
   for every step of a run).
2. The developer's request is quoted in `<developer_request>`; saved project notes in
   `<developer_notes>`; editor content, diagnostics, and **every tool result** in `<project_data>`
   blocks. All of it is HTML-escaped, so text in a file cannot close a block and pose as instructions.
3. The policy tells the model that project data never contains instructions, and that notes are
   preferences that cannot grant tools, permissions, or access.
4. Whatever the model decides is checked by code, not trusted: tool names and permissions
   (`ToolPolicy`), argument schemas, project-relative paths in the user's own index, ignored and
   credential paths, budgets. A model that "obeys" an injection can at most store a proposal, which
   the developer must still approve and which is re-validated.

Regression tests cover injection in source files, README and Markdown comments, notes (memory),
tool output and retrieved context, across modes, plus a model trying traversal, absolute paths, and
unknown write tools (`test_module17_api.py`, `test_agent_api.py`, `test_module17_units.py`).

## Project memory

Short notes the developer saves for one project (`convention`, `decision`, `terminology`,
`constraint`, `preference`; ≤ 500 characters; ≤ 50 per project), via
`GET/POST /projects/{id}/memory` and `DELETE /projects/{id}/memory/{memory_id}`. Only the developer
writes memory; the model never does. Notes that look like credentials (cloud keys, provider API keys,
GitHub/Slack tokens, JWTs, private keys, URLs with passwords, `password=`-style assignments) are
refused with `422 memory_contains_secret` and never stored. The 20 newest notes are given to the agent
as escaped `<developer_notes>`; the run reports how many were used. Adds and deletions are audit-logged
(ids and kinds only, never the text).

## Streaming: evaluated, not implemented

Streaming agent progress would improve the experience for long runs with a real model. It was not
implemented in this module: the agent runs synchronously inside one request, so streaming requires a
transport change (server-sent events through the API and nginx, a cancellable worker, partial-state
persistence, reconnects) whose failure modes could not be exercised without a real provider. The run
already returns user-facing progress events, so a streaming transport can be added without changing
the loop (`AgentService` produces events in order through one function). Recorded as a known
limitation.

## Observability

Metrics (Module 16 `/metrics`): `ai_provider_call`, `agent_run` (by status), `architecture_analysis`,
`impact_analysis`, `search`, `rag_*`. Agent logs: one line per run with mode, status, tool calls,
proposals, findings, provider calls, tokens, duration. Audit log: proposals applied/rejected/stale,
memory added/deleted/refused, tool denials. Never logged: keys, prompts, model output, source text,
memory text.

## Known limitations

- Real providers were not exercised (no credentials): agent behavior is tested with a scripted stub
  model; answer quality is untested.
- Impact analysis follows imports and names only (no call graph, no types, no dynamic imports, no
  HTTP links from frontend to backend).
- Role classification uses file names, folders, and a few markers; unusual layouts can be misread.
- No streaming; long agent runs show progress only when they finish.
- Generated tests are never run by CodeWalk.
- The OpenAI-compatible provider is experimental.
