# Backend test image (Module 14): runs the backend's lint, type checks, tests, and migration
# checks on Linux, next to the docker-compose PostgreSQL (pgvector). Used by
# `npm run test:all:docker`, and on hosts where the PostgreSQL driver cannot load natively
# (for example Windows with Application Control blocking psycopg's binary).
#
# Build context: backend/  (see backend/.dockerignore). Nothing here is a production image.
FROM node:22-bookworm-slim

# uv installs the pinned Python and the locked dependencies. Node is needed by the
# TypeScript analyzer worker that the analysis tests exercise.
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /work/backend
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
COPY tools/typescript-analyzer/package.json tools/typescript-analyzer/package-lock.json tools/typescript-analyzer/
RUN npm --prefix tools/typescript-analyzer ci --no-audit --no-fund
COPY . .
RUN uv sync --frozen

# The default runs the full backend gate; the regression script passes its own command.
CMD ["sh", "-c", "uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy && uv run pytest -p no:cacheprovider"]
