# AI providers (Module 19)

CodeWalk uses **one** AI provider at a time, chosen with `CODEWALK_AI_PROVIDER`. There is no
automatic fallback: if the selected provider fails, the request fails with a normalized error and no
other provider is called. Semantic retrieval (RAG) is separate: it always uses the embedding
provider (`RAG_EMBEDDING_PROVIDER=voyage`, `VOYAGE_API_KEY`), whichever LLM provider is selected.

## Configuration

| `CODEWALK_AI_PROVIDER` | Key (or `CODEWALK_AI_API_KEY`) | Model | Base URL |
| --- | --- | --- | --- |
| `anthropic` (default) | `ANTHROPIC_API_KEY` | `CODEWALK_AI_MODEL` (default `claude-opus-5-5`) | Anthropic SDK |
| `openai` | `OPENAI_API_KEY` | `CODEWALK_AI_MODEL` | `CODEWALK_AI_BASE_URL` (optional, https; http for localhost) |
| `gemini` | `GEMINI_API_KEY` | `CODEWALK_AI_MODEL` | fixed: `https://generativelanguage.googleapis.com/v1beta/openai` |
| `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL`, else `CODEWALK_AI_MODEL` | `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`, https only) |
| `ollama` | none | `OLLAMA_MODEL`, else `CODEWALK_AI_MODEL` | `OLLAMA_BASE_URL` (default `http://localhost:11434`) |

- No model is assumed except Anthropic's default. Without a model (or a required key) the provider
  reports itself as not configured and no call is made.
- Model names may contain only letters, digits and `. _ : / @ + -` (for example `gpt-5`,
  `gemini-2.5-pro`, `vendor/model`, `llama3.1:8b`).
- `CODEWALK_AI_ALLOWED_MODELS` (optional, comma-separated): when AI is enabled and the list is set, the
  server refuses to start with a model outside it.
- Base URLs must not contain credentials. In production `OLLAMA_BASE_URL` must be `https://` or
  localhost: prompts contain project source code and never cross a network in plain HTTP.
- Ollama is for local or self-hosted use and is never required. On Vercel it is reachable only if you
  run it behind an https URL yourself. From Docker Compose use `http://host.docker.internal:11434`.

## Differences handled per provider

All five return one JSON object per request that matches a schema; the server validates it again.

| | OpenAI | Gemini | OpenRouter | Ollama | Anthropic |
| --- | --- | --- | --- | --- | --- |
| Output limit field | `max_completion_tokens` | `max_tokens` | `max_tokens` | `max_tokens` | SDK `max_tokens` |
| Invalid key | 401 | 400 `API_KEY_INVALID` | 401 | n/a | 401 |
| No credit | 429 `insufficient_quota` | 429 | 402 | n/a | 400/429 |
| Upstream failure | 5xx | 5xx | 5xx, or 200 with an `error` object / `finish_reason: error` | 5xx | 5xx |
| Unknown model | 404 | 404 | 404/400 | 404 ("pull it first") | 404 |
| Usage | tokens | tokens | tokens + `cost` (stored as `cost_microusd`) | tokens | tokens |

Normalized errors: `ai_timeout` (504), `ai_rate_limited` (429), `ai_unavailable` (503, also for an
unreachable server: connecting gives up after 10 s), `ai_provider_error` (502: rejected key, no
credit, unknown model, rejected request), `ai_malformed_response` (502), `ai_context_too_large` (413),
`ai_refused` (422). Provider messages, keys and payloads are never returned or logged.

**Streaming and native tool calling are not used.** The agent asks for one structured JSON step at a
time and the server itself checks, authorizes and runs each tool (read-only tools, a budget, and code
changes only as proposals that a user must approve, with stale-patch checks). So every provider
supports the agent in the same way, and no provider can bypass tool authorization or approval.
Structured output (`response_format: json_schema`) must be supported by the chosen model; on
OpenRouter and Ollama that depends on the model, and an unsupported one fails with a normalized error.

## Limits

| Limit | Setting | Default |
| --- | --- | --- |
| Prompt size (system + user) | `CODEWALK_AI_MAX_INPUT_CHARS` | 400,000 characters; larger requests fail with 413 before any call |
| Output tokens | `CODEWALK_AI_MAX_TOKENS` | 16,000 |
| Time per request | `CODEWALK_AI_TIMEOUT_SECONDS` | 90 s (connect: 10 s) |
| Requests per user | `CODEWALK_AI_MAX_REQUESTS` / `CODEWALK_AI_WINDOW_SECONDS` | 30 per 10 minutes |
| Agent runs per user | `CODEWALK_AGENT_MAX_RUNS` / `CODEWALK_AGENT_WINDOW_SECONDS` | 20 per 10 minutes |

Requests are not retried automatically: an AI call costs money, and the user can retry.

## Testing

`tests/test_ai_providers_multi.py` (no database) and `tests/db/test_multi_provider_agent.py` (agent
and proposal workflow over Gemini, OpenRouter and Ollama) run each provider's real HTTP code against a
mock transport. No live provider call has been made; `tests/test_live_ai_provider.py` (Anthropic only)
runs only when a credential is configured.
