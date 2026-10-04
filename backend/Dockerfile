# CodeWalk Agent backend: production image (Module 15).
#
# Build context: backend/   (see backend/.dockerignore)
#   docker build -t codewalk-backend backend
#
# Stages:
#   python-deps  locked runtime dependencies (no dev group) in /opt/venv
#   ts-tools     the TypeScript analyzer worker's npm dependencies
#   runtime      python:3.12-slim + venv + Node binary + application code, non-root
#
# Nothing secret is baked in: configuration comes from CODEWALK_* environment variables at run
# time (see docs/deployment/environment.md). The same image runs the API and the one-shot
# migration job (`alembic upgrade head`).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim

FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM ${PYTHON_IMAGE} AS python-deps
COPY --from=uv /uv /usr/local/bin/uv
# Use the image's Python (the runtime stage has the same one) and never download another.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1
WORKDIR /build
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

FROM ${NODE_IMAGE} AS ts-tools
WORKDIR /build/tools/typescript-analyzer
COPY tools/typescript-analyzer/package.json tools/typescript-analyzer/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM ${NODE_IMAGE} AS node-binary

FROM ${PYTHON_IMAGE} AS runtime
# Node runs the TypeScript analyzer worker (a single binary; its libraries are in the base image).
COPY --from=node-binary /usr/local/bin/node /usr/local/bin/node
RUN groupadd --system --gid 10001 codewalk \
    && useradd --system --uid 10001 --gid codewalk --home-dir /app --no-create-home --shell /usr/sbin/nologin codewalk
COPY --from=python-deps /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root migrations ./migrations
COPY --chown=root:root app ./app
COPY --chown=root:root tools/typescript-analyzer/analyzer.mjs tools/typescript-analyzer/package.json ./tools/typescript-analyzer/
COPY --from=ts-tools --chown=root:root /build/tools/typescript-analyzer/node_modules ./tools/typescript-analyzer/node_modules

# Code is owned by root and read-only to the service user; the app writes nothing to disk.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODEWALK_ENV=production \
    CODEWALK_HOST=0.0.0.0 \
    CODEWALK_PORT=8000 \
    CODEWALK_NODE_BINARY=/usr/local/bin/node

USER codewalk:codewalk
EXPOSE 8000

# Readiness (database check included); see docs/deployment/architecture.md for the endpoints.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; port = os.environ.get('CODEWALK_PORT', '8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health/ready', timeout=4).status == 200 else 1)"]

# uvicorn (via app.__main__): no reload outside development; proxy headers trusted in production
# from FORWARDED_ALLOW_IPS. SIGTERM triggers a graceful shutdown.
CMD ["python", "-m", "app"]
