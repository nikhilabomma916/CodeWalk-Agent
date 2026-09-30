# CodeWalk Agent

CodeWalk Agent is an AI-assisted coding environment: a browser-based IDE that helps developers
write, understand, debug, and improve code, and eventually understand whole projects through
deterministic analysis, project intelligence, retrieval-augmented generation (RAG), and AI agents.

> **Status:** Batch 1 of 6 is complete (foundation, frontend editor, backend API). Features listed
> under *Planned* are **not implemented yet**.

## Capabilities

### Implemented

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
- **Problems panel**: shows the editor's built-in *syntax* diagnostics (TypeScript/JavaScript,
  JSON, CSS) with click-to-navigate. It runs no project analysis yet.
- **Backend API** (FastAPI): versioned `/api/v1`, health/readiness endpoints, a structured error
  contract, request IDs, CORS allow-list, body-size limits, and OpenAPI docs.
- **Real connection status**: the status bar polls `GET /api/v1/health` and shows
  online / degraded / unavailable / offline / not responding / error. It never assumes success.

### Planned (future batches)

Real-time code analysis (Ruff, Pylint, Mypy, …) → diagnostics integration → project intelligence
(AST, symbols, relationships) → server-side project/file management → PostgreSQL persistence → AI
explanations and fixes with a diff/approval workflow (AI never silently overwrites code) → project
search → RAG → multi-agent assistance → authentication → Docker deployment.

## Architecture

```
Browser ── Next.js frontend (features/*, services/api) ──HTTP /api/v1──▶ FastAPI backend
                                                                          ├─ api/routes     (thin HTTP layer)
                                                                          ├─ services       (business logic)
                                                                          ├─ repositories   (data access, Module 8)
                                                                          └─ integrations   (external services, e.g. AI)
```

See [docs/architecture.md](docs/architecture.md) for the design and extension points, and
[docs/api.md](docs/api.md) for the API contract.

## Technology

| Area     | Stack |
| -------- | ----- |
| Frontend | Next.js 16 (App Router, Turbopack), React 19, TypeScript (strict), Tailwind CSS 4, Monaco Editor 0.57 (self-hosted), zod, react-resizable-panels |
| Backend  | Python 3.12, FastAPI, Pydantic 2, pydantic-settings, Uvicorn, httpx |
| Quality  | ESLint, Prettier, Vitest, Testing Library · Ruff (lint + format), Mypy (strict), Pytest |
| Tooling  | uv (Python), npm (Node) |

## Repository structure

```
.
├── frontend/                Next.js application
│   ├── app/                 routes, root layout, global styles/theme
│   ├── components/ui/       reusable UI primitives (dialogs, buttons, states)
│   ├── features/            feature modules: workspace, explorer, editor, problems, status-bar, …
│   ├── lib/                 framework-free helpers (config, languages, path utilities)
│   ├── services/api/        typed HTTP client and endpoint wrappers
│   ├── types/               shared domain types (diagnostics, project tree)
│   └── scripts/             build helpers (copies Monaco assets into public/)
├── backend/
│   ├── app/
│   │   ├── api/             router + routes + dependency providers
│   │   ├── core/            config, logging, exceptions, middleware
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── services/        business logic (health)
│   │   ├── integrations/    resilient external HTTP client
│   │   └── utils/           safe path handling
│   └── tests/               backend unit/API tests
├── tests/integration/       live-stack tests (require running services)
├── scripts/                 developer scripts (dev launcher)
├── docs/                    architecture and API documentation
├── .env.example             documented configuration template
└── package.json             root task runner
```

## Development setup

**Prerequisites:** Node.js ≥ 20.9 and [uv](https://docs.astral.sh/uv/). uv installs the pinned
Python 3.12 automatically.

```bash
npm run setup            # npm install (frontend) + uv sync (backend, creates backend/.venv)
cp .env.example .env     # optional: defaults work for local development
```

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
| `CODEWALK_DATABASE_URL`, `CODEWALK_AI_*` | read by settings; reserved for the persistence/AI modules |
| `NEXT_PUBLIC_API_BASE_URL` | backend API base URL used by the browser |

Production startup fails fast on an insecure configuration (missing or weak secret key, wildcard CORS).
Interactive API docs are disabled in production unless `CODEWALK_DOCS_ENABLED=true`.

## Running

```bash
npm run dev              # backend (:8000) and frontend (:3000) together; Ctrl+C stops both
# or separately:
npm run dev:backend      # uv run python -m app   (auto-reload in development)
npm run dev:frontend     # next dev
```

- Frontend: <http://localhost:3000>
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

## Development workflow

- Branches: `main` (stable) ← `develop` (integration) ← `feature/*`.
- Run `npm run check` before opening a pull request.
- Keep business logic out of route handlers and UI components: routes → services → repositories;
  components → feature hooks/context → `services/api`.
- Never hardcode secrets. Uploaded or opened source code is never executed.
