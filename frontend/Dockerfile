# CodeWalk Agent frontend: Next.js images (Module 15).
#
# Build context: frontend/   (see frontend/.dockerignore)
#   docker build -t codewalk-frontend frontend                 # production (default target)
#   docker build --target dev -t codewalk-frontend-dev frontend
#
# Stages:
#   deps     npm ci from the lockfile (all dependencies: the build needs the dev tooling)
#   dev      development server, source mounted by docker-compose.yml (profile "app")
#   builder  next build -> .next/standalone (Monaco copied into public/ by the prebuild step)
#   runtime  node + the standalone server only, non-root
#
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time, so only public
# configuration may be passed as build arguments. Provider keys and other secrets are
# backend-only and never reach this image.

ARG NODE_IMAGE=node:22-bookworm-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1 \
    WATCHPACK_POLLING=true
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM deps AS builder
# Same-origin API path behind the reverse proxy: one image serves any domain.
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ARG NEXT_PUBLIC_API_TIMEOUT_MS=10000
ARG NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS=15000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_API_TIMEOUT_MS=${NEXT_PUBLIC_API_TIMEOUT_MS} \
    NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS=${NEXT_PUBLIC_HEALTH_POLL_INTERVAL_MS} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
# Root-owned, read-only application files; the server runs as the image's unprivileged "node" user.
COPY --from=builder --chown=root:root /app/.next/standalone ./
COPY --from=builder --chown=root:root /app/.next/static ./.next/static
COPY --from=builder --chown=root:root /app/public ./public
# Next.js writes its runtime cache under .next/cache; nothing else is writable.
RUN mkdir -p .next/cache && chown node:node .next/cache
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:' + (process.env.PORT || 3000) + '/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
# server.js handles SIGTERM; tini (compose `init: true`) forwards signals and reaps children.
CMD ["node", "server.js"]
