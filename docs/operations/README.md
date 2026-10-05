# Operations (Module 16)

Observability, concurrency and limits, background-processing decisions, known limitations, and
production recommendations. Deployment itself is described in [../deployment/](../deployment/).

## Observability

### Logs

One line per event, JSON in production (`CODEWALK_LOG_FORMAT=json`), each with the request id that
is also returned in the `X-Request-ID` header and in every error response.

| Logger | What |
| --- | --- |
| `app.access` | every request: method, path, status, duration |
| `app.security` | authentication failures, rate limiting, cross-user access attempts, origin rejections, agent tool denials, proposal decisions (identifiers, codes and counts only) |
| `app.services.agent.service` | agent run start/finish: status, tool calls, proposals, duration |
| `app.services.retrieval.service` | indexing runs: files, chunks embedded/reused, tokens |
| `app.errors` | unhandled exceptions (the client receives a generic 500 with the request id) |

Never logged: passwords, session tokens, API keys, `Authorization` headers, file contents, model
prompts or answers. `httpx` is held at WARNING so provider URLs are not logged.

### Metrics

`GET /metrics` on the backend returns Prometheus text (`CODEWALK_METRICS_ENABLED`, default on).
It is outside `/api`, so the reverse proxy (which routes only `/api/`) never exposes it; scrape it
from the stack's internal network, e.g. `http://backend:8000/metrics`. The deployment smoke test
checks that `/metrics` is not reachable through the proxy.

| Metric | Labels |
| --- | --- |
| `codewalk_http_request_duration_seconds` (histogram) | `method`, `route` (the route **template**, e.g. `/api/v1/projects/{project_id}`; `unmatched` otherwise), `status` (`2xx`...) |
| `codewalk_operation_duration_seconds` (histogram) | `operation`, `outcome` (below) |
| `codewalk_db_statement_duration_seconds` (histogram) | none |
| `codewalk_process_start_time_seconds` (gauge) | none |

| Operation | Outcomes |
| --- | --- |
| `code_analysis` | `ok`, `partial`, `error` |
| `search` | the mode actually used: `deterministic`, `semantic`, `hybrid`; `error` |
| `search_index_build` | `full`, `incremental` |
| `rag_index`, `rag_document_embedding`, `rag_query_embedding` | `ok`, `error` |
| `ai_provider_call` | `ok`, `error` |
| `agent_run` | `completed`, `limit_reached`, `failed` |

Bounded by construction: labels come from fixed sets (route templates, operation names, status
classes), never from ids, paths, emails or other input; each metric is additionally capped at 500
series (excess goes to an `_other` series). Counts are per process: with several workers, sum them.

Useful queries: p95 latency per route
(`histogram_quantile(0.95, sum by (le, route) (rate(codewalk_http_request_duration_seconds_bucket[5m])))`),
error rate (`status="5xx"`), provider failure rate (`operation="ai_provider_call", outcome="error"`).

## Concurrency and rate limits

| Concern | Behavior |
| --- | --- |
| Simultaneous approvals of one proposal | The action row is locked: exactly one succeeds, the others get 409 (`test_simultaneous_approvals_apply_a_proposal_once`). |
| Simultaneous approvals of different proposals for one file | The file row is locked too: one is applied, the other is `stale` (409); no change is overwritten (`test_different_proposals_for_one_file_cannot_both_apply`). |
| Parallel saves of one file | Version numbers stay unique and gap-free; a conflicting save gets 409 (`test_parallel_saves_to_one_file_keep_versions_consistent`). |
| Rate limits under concurrency | Checked and recorded atomically: N simultaneous requests cannot exceed the limit (`test_simultaneous_agent_runs_cannot_exceed_the_run_limit`, `test_acquire_admits_exactly_the_limit_under_concurrency`). |
| One SQL statement | Cancelled by PostgreSQL after `CODEWALK_DATABASE_STATEMENT_TIMEOUT_SECONDS` (30 s). |

**Rate limits are process-local.** Each API process keeps its own counters (login 10/15 min,
registration 20/h, AI 30/10 min, agent 20/10 min, semantic queries 120/10 min, index runs 10/10 min).
With several processes a client can make up to *processes x limit* attempts, and a restart clears
the counters. This is not distributed protection; a shared store (for example Redis) or limits at
the reverse proxy would be needed for that. The default deployment runs one backend process.

## Caching decisions

| Cache | Key | Invalidation | Bound | Isolation |
| --- | --- | --- | --- | --- |
| Project search index (in memory) | project id; valid while every file's (path, content hash) matches | any changed hash; the next index reuses unchanged files (incremental) | 32 projects per process (LRU) | built only after the ownership check; contains one project's files |
| Per-file structure (`files.structure`) | file + content hash + structure version | content change | one per file | row of the owner's file |
| Query embeddings | (model, query text) | none needed (pure function of the text) | 256 entries | holds vectors only, no project data |
| Stored chunk vectors (`code_chunks`) | file + model + chunk hash | file content hash; replaced on the next index run | per project | filtered by project id |

Not cached, deliberately: project listings, file contents and diagnostics are single indexed
queries (5-20 ms measured); deterministic search results depend on the query, filters and the open
file, and the index they are computed from is already cached. Redis was not introduced: every
cache above is either process-local by nature or already in PostgreSQL, and one process is the
default deployment.

## Background processing decisions

No job system was added. Measured with the stub embedder, a full semantic index of 2,000 files
takes about 12 s in one request; runs are bounded (`RAG_MAX_CHUNKS_PER_RUN`, default 2,000 chunks,
commits every 256 chunks, reports `remaining_files`); the search panel tells the developer to run it
again while files remain, and each request stays within the proxy timeout. Folder rescans of 2,000 files take about 0.9 s. A queue would add
job ids, status storage, retries and cancellation for operations that already finish within
normal request limits. Revisit if real embedding latency makes a 2,000-chunk run approach the
proxy read timeout (120 s).

## Known limitations

- Rate limits and in-memory caches are per process (see above).
- Real AI and embedding providers were never measured or exercised here (no credentials); all
  provider-dependent numbers exclude provider latency.
- The intelligence view returns every file's symbols and relationships (about 5 MB for a
  2,000-file synthetic project, ~0.5 s); it is not paginated.
- Deterministic (and hybrid) search examines every indexed file in Python on each query; the
  1,000 best-ranked candidates are kept. Time grows linearly with project size.
- A full semantic index is dominated by PostgreSQL maintaining the HNSW index.
- Measurements come from one Windows machine running Docker Desktop (WSL2); they show relative
  improvement and scaling, not production capacity.

## Production recommendations

1. Scrape `/metrics` from the internal network; alert on `5xx` rate, p95 of
   `/api/v1/projects/{project_id}/search` and `/api/v1/agent/run`, and `ai_provider_call` errors.
2. Keep one backend process unless rate limits move to a shared store; scale vertically first.
3. Run `alembic upgrade head` before starting a new version (migration `9c4d2b7a1e83` builds its
   indexes concurrently and does not block writes).
4. Keep `CODEWALK_DATABASE_STATEMENT_TIMEOUT_SECONDS` below the proxy read timeouts.
5. Measure real provider latency once credentials exist (`tests/test_live_*`), then revisit the
   background-processing decision for semantic indexing.
