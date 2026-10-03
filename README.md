# CodeWalk Agent

CodeWalk Agent is an AI-assisted coding environment: a browser-based IDE that helps developers
write, understand, debug, and improve code, and eventually understand whole projects through
deterministic analysis, project intelligence, retrieval-augmented generation (RAG), and AI agents.

> **Status:** Batches 1–4 and Module 10 are complete: foundation, editor, and API (Modules 1–3);
> code analysis, project intelligence, and PostgreSQL persistence (Modules 4–6); accounts,
> application areas, and project ownership (Batch 3); AI code analysis, AI explanations and fix
> suggestions, and project-aware search (Modules 7–9); semantic retrieval with hybrid ranking
> (Module 10). Features listed under *Planned* are **not implemented yet**.

## Capabilities

### Implemented

- **Accounts**: registration, sign-in, sign-out, and session handling. Passwords are hashed with
  Argon2id, and the session is an opaque token in an `httpOnly`, `SameSite=Lax` cookie (only its
  SHA-256 is stored). Failed sign-ins and registrations are rate limited.
- **Application areas** (signed-in users only): **Coding** (`/app/coding`), **Projects**
  (`/app/projects`, `/app/projects/[projectId]`), and **History** (`/app/history`), with a navigation
  rail (a top bar on small screens) and an account menu. Open files and unsaved edits are kept while
  moving between areas.
- **Project ownership**: every project, file, analysis, version, and history entry belongs to one
  user. The API checks ownership on every request, and another user's project is answered as
  "not found".
- **Projects area**: your projects with real statistics (files, lines, languages, last analysis),
  create / edit / delete, a project page with an explorer (files and, after analysis, symbols) that
  opens files in Coding, and project analysis.
- **History**: activity recorded as it happens (projects created/renamed/deleted/analyzed, files
  created/saved/restored/deleted/analyzed, with problem counts and file versions), grouped by day,
  filterable by project and activity, with details that link back to the project and file.
- **AI code review (Module 7, optional)**: an *AI Review* tab reviews the open file, including unsaved
  edits, together with its deterministic diagnostics. It can focus on general review, likely bugs,
  quality, security, or performance, or explain the code. Findings link to lines and are labelled
  *observed* or *inferred*, with the model's own confidence. All AI output is shown as advisory.
- **AI explanations and fix suggestions (Module 8, optional)**: in the Problems panel, *Explain* gives
  the meaning, likely cause, impact, and fix for a diagnostic. *Suggest a fix* opens a side-by-side
  diff (current vs. suggested) with **Apply fix / Reject / Close review**. Nothing changes until you
  apply. Applying changes the editor only (undoable; you then save), and only if the file still
  matches what the suggestion was computed against.
- **Project-aware search (Module 9)**: *Search* in the Coding sidebar (`Ctrl+Shift+F`) finds
  functions, classes, methods, files, imports, identifiers, and text in a server project, with
  language and symbol-type filters. Ranking is deterministic and explained (not semantic), and the
  open file and files related to it by imports rank higher. Clicking a result opens the file at that
  line. The same context builder supplies related code to the AI features.
- **Semantic retrieval (Module 10, optional)**: code embeddings (Voyage AI `voyage-code-4`) stored in
  PostgreSQL with pgvector. Deterministic search stays the default and is unchanged. When retrieval is
  available, the Search sidebar offers *Include semantic matches* (hybrid ranking: the deterministic
  and semantic lists are merged by reciprocal rank fusion) and an explicit *Index project* action.
  The AI features receive semantically similar code from other files after the deterministic
  context. See [Semantic retrieval](#semantic-retrieval-enabling-it).
- **File versions**: each saved content change of a server file is kept as a numbered version (newest
  50 per file by default) and can be viewed or restored through the API.
- **Coding workspace** (Next.js + Monaco): project explorer, multi-file tabs, syntax highlighting for
  25+ languages, language auto-detection with manual override, find, format (where Monaco has a
  formatter), undo/redo, word wrap, minimap, folding, bracket matching, and resizable panels.
- **Projects in the browser**:
  - *New project*: in-memory; files live in the current tab.
  - *Open folder* (Chromium browsers): real read/write access through the File System Access API.
    **Save writes to disk.**
  - *Open folder* (other browsers): read-only copy; saved changes stay in the tab.
  - Dependency/build folders (`node_modules`, `.venv`, `dist`, …) and `.env` files are skipped.
- **Unsaved-change safety**: dirty indicators, a Save / Don't save / Cancel prompt on tab close, a
  prompt before replacing a project, and a browser warning before leaving the page.
- **Real-time code analysis**: while you type (450 ms debounce; stale responses are discarded), the
  backend analyzes the active file without executing it. It uses Python `ast` + Ruff, the
  TypeScript compiler for TS/JS, strict JSON, structural HTML checks, tree-sitter for Java/C/C++/CSS,
  sqlglot for SQL, and Markdown lint rules. Results show as Monaco markers and in the **Problems
  panel** (click to jump to the location), next to Monaco's built-in syntax diagnostics.
- **Project intelligence**: for server projects, a deterministic analysis of files, languages,
  symbols (Python AST; JS/TS via tree-sitter), imports, file-to-file relationships, and statistics.
  Malformed files are reported without stopping the analysis. Folder-linked projects are scanned
  safely: no symlinks, secrets, or dependency folders, and `.gitignore` is honoured.
- **Persistence** (PostgreSQL + SQLAlchemy + Alembic): projects, files, analyses, and diagnostics,
  with project/file CRUD APIs and analysis history. Server projects open in the editor and save to
  the database. Without a database the app still runs, and persistence reports itself unavailable.
- **Backend API** (FastAPI): versioned `/api/v1`, health/readiness endpoints, a structured error
  contract, request IDs, CORS allow-list, body-size limits, and OpenAPI docs.
- **Real connection status**: the status bar polls `GET /api/v1/health` and shows
  online / degraded / unavailable / offline / not responding / error. It never assumes success.

### Planned (future batches)

Multi-agent assistance → Docker deployment. Account management (password change/reset, email
verification, settings) is not implemented yet.

### AI assistance: enabling it

AI is **off by default**, and CodeWalk works fully without it. To enable it, set
`CODEWALK_AI_ENABLED=true` and a server-side credential (`ANTHROPIC_API_KEY`) in your local `.env`,
then restart the backend. The only provider implemented is Anthropic (Claude; default model
`claude-opus-5-5`, via the official `anthropic` SDK). Other providers plug in behind the same
`AIProvider` interface. The key stays on the server: it is never sent to the browser, returned by the
API, or logged. Without it, `GET /api/v1/ai/status` explains what is missing, and the UI shows
"AI unavailable" instead of results.

### Semantic retrieval: enabling it

Semantic retrieval is **off by default**; deterministic search and the AI features work without it.
To enable it, set `RAG_ENABLED=true` and `VOYAGE_API_KEY` in your local `.env` (server-side only),
then restart the backend. `GET /api/v1/rag/status` reports what is missing, without calling the
provider and without returning the key.

- **Provider**: Voyage AI through its REST API (`EmbeddingProvider` → `VoyageEmbeddingProvider`;
  other providers register behind the same interface). Default model `voyage-code-4`
  (`RAG_EMBEDDING_MODEL`), 1024 float dimensions. Code chunks are embedded as `document`, searches
  as `query`.
- **Indexing is explicit**: *Index project* (or `POST /api/v1/projects/{id}/rag/index`) sends new and
  changed files to the provider. **This sends the project's source code to Voyage AI.** Files are split
  along the Module 5 symbols (functions, classes, methods; other lines in 40-line windows), bounded in
  size. Ignored folders and secret files are never indexed. Unchanged chunks keep their vectors, so
  re-indexing after an edit only embeds what changed. One run embeds at most
  `CODEWALK_RAG_MAX_CHUNKS_PER_RUN` chunks; `remaining_files` says whether to run again.
- **Freshness**: a file edited after indexing is excluded from semantic results (its stored chunks
  no longer match its content hash) until it is indexed again, and the search response warns about it.
- **Search modes** (`mode` on `POST /api/v1/projects/{id}/search`): `deterministic` (default,
  Module 9), `semantic` (cosine similarity), `hybrid` (RRF, `score = Σ 1/(60 + rank)`; results carry
  their ranks in `fusion`). Without retrieval, the request still succeeds with deterministic results,
  `mode_used: "deterministic"`, and a warning.
- **AI context**: after the four deterministic context steps, up to 4 semantically similar snippets
  from other files fill the remaining budget (reason `semantically similar (cosine similarity …)`).
  A retrieval failure never fails an AI request; the context stays deterministic.

This is retrieval for search and AI context only: there is no autonomous agent, and nothing is executed.

## Architecture

```
Browser ── Next.js frontend (features/*, services/api) ──HTTP /api/v1──▶ FastAPI backend
                                                                          ├─ api/routes     (thin HTTP layer)
                                                                          ├─ services       (business logic)
                                                                          ├─ repositories   (data access, SQLAlchemy)
                                                                          ├─ db + migrations (PostgreSQL, Alembic)
                                                                          └─ integrations   (external services, e.g. AI)
```

See [docs/architecture.md](docs/architecture.md) for the design and extension points, and
[docs/api.md](docs/api.md) for the API contract.

## Technology

| Area     | Stack |
| -------- | ----- |
| Frontend | Next.js 16 (App Router, Turbopack), React 19, TypeScript (strict), Tailwind CSS 4, Monaco Editor 0.57 (self-hosted), zod, react-resizable-panels |
| Backend  | Python 3.12, FastAPI, Pydantic 2, pydantic-settings, Uvicorn, httpx, SQLAlchemy 2, Alembic, psycopg 3 |
| Analysis | Ruff, TypeScript compiler (Node worker), tree-sitter, sqlglot |
| Database | PostgreSQL 17 (Docker Compose for development) |
| Quality  | ESLint, Prettier, Vitest, Testing Library · Ruff (lint + format), Mypy (strict), Pytest |
| Tooling  | uv (Python), npm (Node) |

## Repository structure

```
.
├── frontend/                Next.js application
│   ├── app/                 routes: / , (auth)/login|register, app/{coding,projects,history}
│   ├── components/ui/       reusable UI primitives (dialogs, buttons, states)
│   ├── features/            feature modules: auth, shell, workspace, projects, history, editor, …
│   ├── lib/                 framework-free helpers (config, languages, path utilities)
│   ├── services/api/        typed HTTP client and endpoint wrappers
│   ├── types/               shared domain types (diagnostics, project tree)
│   └── scripts/             build helpers (copies Monaco assets into public/)
├── backend/
│   ├── app/
│   │   ├── api/             router + routes + dependency providers
│   │   ├── core/            config, logging, exceptions, middleware
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── services/        business logic (auth, activity, analysis, project_intelligence, projects, files)
│   │   ├── repositories/    data access (users, projects, files, versions, analyses, activity)
│   │   ├── db/              SQLAlchemy models, engine/session
│   │   ├── integrations/    resilient external HTTP client
│   │   └── utils/           safe path handling
│   ├── migrations/          Alembic migrations
│   ├── tools/               TypeScript analyzer worker (Node)
│   └── tests/               backend unit/API tests; tests/db runs against real PostgreSQL
├── tests/integration/       live-stack tests (require running services)
├── scripts/                 developer scripts (dev launcher)
├── docker/                  PostgreSQL init scripts
├── docs/                    architecture and API documentation
├── docker-compose.yml       local PostgreSQL
├── .env.example             documented configuration template
└── package.json             root task runner
```

## Development setup

**Prerequisites:** Node.js ≥ 20.9, [uv](https://docs.astral.sh/uv/) (installs the pinned Python
3.12 automatically), and Docker (for PostgreSQL).

```bash
npm run setup                        # npm install (frontend + TypeScript analyzer worker), uv sync (backend)
cp .env.example .env                 # includes working local database URLs
npm run db:up                        # PostgreSQL 17 + pgvector in Docker (creates codewalk + codewalk_test)
npm run db:migrate                   # alembic upgrade head
```

Then open <http://localhost:3000> and create an account on the registration page. There are no
built-in or seeded users. The tests create their own throw-away users.

**Upgrading a database from Batch 2:** projects now need an owner. If the database contains
projects created before accounts existed, `alembic upgrade head` stops and explains this. Run
`uv --directory backend run alembic -x delete_unowned_projects=true upgrade head` to delete them
(with their files and analyses) and continue.

**Upgrading the database image (Module 10):** `docker-compose.yml` now uses
`pgvector/pgvector:pg17-bookworm` instead of `postgres:17-alpine`. The data volume is reused as is
(same PostgreSQL 17 data directory). Because Alpine (musl) and Debian (glibc) sort text differently,
rebuild the text indexes once after switching, then migrate:

```bash
docker compose exec postgres pg_dumpall -U codewalk > backup.sql   # before switching (optional, recommended)
docker compose up -d --wait postgres                                # recreates the container on the new image
docker compose exec postgres psql -U codewalk -d codewalk -c "REINDEX DATABASE codewalk;"
docker compose exec postgres psql -U codewalk -d codewalk_test -c "REINDEX DATABASE codewalk_test;"
npm run db:migrate                                                  # adds the vector extension and code_chunks
```

The migration runs `CREATE EXTENSION IF NOT EXISTS vector`, which needs pgvector installed on the
server (it is in the image above).

Without Docker, leave `CODEWALK_DATABASE_URL` empty. The editor and code analysis still work, and
server projects report that persistence is unavailable. Use `127.0.0.1` rather than `localhost` in
database URLs: on Windows, `localhost` tries IPv6 first and stalls against the container port.

### Environment configuration

All configuration comes from environment variables; `.env.example` documents every one.
The repository-level `.env` is read by both the backend and the frontend (`backend/.env` or
`frontend/.env.local` can override per service). `.env` files are git-ignored. Never commit them.

| Variable | Purpose |
| --- | --- |
| `CODEWALK_ENV` | `development` \| `testing` \| `production` |
| `CODEWALK_HOST`, `CODEWALK_PORT` | backend bind address (used by `python -m app`) |
| `CODEWALK_CORS_ORIGINS` | comma-separated frontend origins; `*` is rejected |
| `CODEWALK_SECRET_KEY` | **required in production** (≥ 32 random chars) |
| `CODEWALK_LOG_LEVEL`, `CODEWALK_LOG_FORMAT` | logging level; `text` or `json` output |
| `CODEWALK_MAX_REQUEST_BODY_BYTES`, `CODEWALK_MAX_UPLOAD_BYTES` | request limits |
| `CODEWALK_DATABASE_URL` | PostgreSQL URL (`postgresql+psycopg://…`); persistence is off when empty |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | used by `docker-compose.yml` |
| `CODEWALK_TEST_DATABASE_URL` | dedicated `*_test` database for `backend/tests/db` (skipped when unset) |
| `CODEWALK_WORKSPACE_ROOT` | server folder whose sub-folders can be linked as projects (disabled when unset) |
| `CODEWALK_MAX_SOURCE_BYTES`, `CODEWALK_ANALYSIS_TIMEOUT_SECONDS`, `CODEWALK_NODE_BINARY` | analysis limits and tooling |
| `CODEWALK_SESSION_TTL_HOURS` | sign-in lifetime (default 168 = 7 days) |
| `CODEWALK_SESSION_COOKIE_NAME`, `CODEWALK_SESSION_COOKIE_SECURE` | session cookie name; `Secure` flag (defaults to on in production only) |
| `CODEWALK_LOGIN_MAX_ATTEMPTS`, `CODEWALK_LOGIN_WINDOW_SECONDS` | failed sign-ins per address + email before HTTP 429 |
| `CODEWALK_REGISTER_MAX_ATTEMPTS`, `CODEWALK_REGISTER_WINDOW_SECONDS` | registrations per address before HTTP 429 |
| `CODEWALK_FILE_VERSION_HISTORY_LIMIT`, `CODEWALK_ANALYSIS_HISTORY_PER_FILE` | versions / analyses kept per file |
| `CODEWALK_AI_ENABLED` | turn AI assistance on (default `false`) |
| `ANTHROPIC_API_KEY` (or `CODEWALK_AI_API_KEY`) | provider credential, **server-side only** |
| `CODEWALK_AI_PROVIDER`, `CODEWALK_AI_MODEL` | `anthropic`; model (default `claude-opus-5-5`) |
| `CODEWALK_AI_TIMEOUT_SECONDS`, `CODEWALK_AI_MAX_TOKENS`, `CODEWALK_AI_EFFORT` | request limits and reasoning effort |
| `CODEWALK_AI_MAX_REQUESTS`, `CODEWALK_AI_WINDOW_SECONDS` | AI requests per user per window (then 429) |
| `RAG_ENABLED` | turn semantic retrieval on (default `false`) |
| `VOYAGE_API_KEY` | embedding provider credential, **server-side only** |
| `RAG_EMBEDDING_PROVIDER`, `RAG_EMBEDDING_MODEL` | `voyage`; model (default `voyage-code-4`) |
| `CODEWALK_RAG_TIMEOUT_SECONDS`, `CODEWALK_RAG_MAX_CHUNKS_PER_RUN` | provider timeout; chunks embedded per indexing run |
| `CODEWALK_RAG_MAX_QUERIES`, `CODEWALK_RAG_MAX_INDEX_RUNS`, `CODEWALK_RAG_WINDOW_SECONDS` | query embeddings and indexing runs per user per window |
| `NEXT_PUBLIC_API_BASE_URL` | backend API base URL used by the browser |

Production startup fails fast on an insecure configuration (missing or weak secret key, wildcard CORS).
In production, serve the frontend and API over HTTPS on the same site (for example `app.example.com`
and `api.example.com`) so the `SameSite=Lax`, `Secure` session cookie is sent. In development they
run on `localhost:3000` and `localhost:8000`, which count as the same site. Open the frontend at
`localhost` (not `127.0.0.1`) to match `NEXT_PUBLIC_API_BASE_URL`.
Interactive API docs are disabled in production unless `CODEWALK_DOCS_ENABLED=true`.

## Running

```bash
npm run dev              # backend (:8000) and frontend (:3000) together; Ctrl+C stops both
# or separately:
npm run dev:backend      # uv run python -m app   (auto-reload in development)
npm run dev:frontend     # next dev
```

- Frontend: <http://localhost:3000> (redirects to `/login`, or to `/app/projects` when signed in)
- API: <http://localhost:8000/api/v1/health>
- API docs (development): <http://localhost:8000/docs>

Production-style frontend: `npm run build:frontend`, then `npm --prefix frontend start`.

## Testing and quality

```bash
npm test                 # backend pytest + frontend vitest
npm run test:integration # live checks: requires `npm run dev` running
npm run lint             # ruff + eslint
npm run typecheck        # mypy (strict) + tsc
npm run format           # ruff format + prettier (write)
npm run check            # lint + format check + typecheck + tests
```

Per service: `cd backend && uv run pytest | ruff check app tests | mypy`, and
`cd frontend && npm run test | lint | typecheck | build`.

**AI tests** never call a paid provider by default. The provider is tested through the real SDK
with a mock HTTP transport, and the AI endpoints use a test-only stub provider (`tests/ai_stub.py`)
to check CodeWalk's own logic. `tests/test_live_ai_provider.py` sends one real request only when a
credential is present in the environment, and is skipped otherwise.

**Retrieval tests** follow the same rule. The Voyage provider is tested with a mock HTTP transport
(request shape, batching, input types, error mapping). The indexing, search, fusion, context, and
ownership tests run on real PostgreSQL + pgvector with `tests/embedding_stub.py`, a test-only
hashed bag-of-words embedder that is **not** a real model and says nothing about retrieval quality.
`tests/test_live_voyage.py` makes real embedding calls only when `VOYAGE_API_KEY` is set.

**PostgreSQL tests** (`backend/tests/db`) run against a real database and are skipped, never faked,
when `CODEWALK_TEST_DATABASE_URL` is unset. They rebuild the schema with the Alembic migrations, so
the database name must end in `_test`:

```bash
npm run db:up
CODEWALK_TEST_DATABASE_URL=postgresql+psycopg://codewalk:codewalk_dev_password@127.0.0.1:5432/codewalk_test \
  uv --directory backend run pytest tests/db
```

## Development workflow

- Branches: `main` (stable) ← `develop` (integration) ← `feature/*`.
- Run `npm run check` before opening a pull request.
- Keep business logic out of route handlers and UI components: routes → services → repositories;
  components → feature hooks/context → `services/api`.
- Never hardcode secrets. Uploaded or opened source code is never executed.
