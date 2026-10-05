# Reverse proxy

nginx 1.28 (`nginxinc/nginx-unprivileged`, runs as uid 101 on ports 8080/8443 inside the container).
Configuration: `deploy/nginx/codewalk/`; the site mode is chosen at start by
`deploy/nginx/40-codewalk-site.sh` from `CODEWALK_PROXY_TLS`.

| File | Contents |
| --- | --- |
| `http-context.conf` | upstreams (Docker DNS, re-resolved), body limits, client timeouts, gzip settings, access log format |
| `locations.conf` | routes, per-route timeouts, JSON error pages |
| `proxy-headers.conf` | headers sent upstream, connect/send timeouts |
| `site-http.conf` | `CODEWALK_PROXY_TLS=off`: HTTP on 8080 |
| `site-https.conf` | `CODEWALK_PROXY_TLS=on`: HTTPS on 8443, 8080 redirects to HTTPS and serves ACME challenges |

Why nginx: see [architecture.md](architecture.md#design-decisions).

## Routes

`/api/` → backend (`backend:8000`); everything else → frontend (`frontend:3000`). These match the
application: every backend route is under `/api/v1`, and the frontend serves pages, `/_next/static`,
the self-hosted editor under `/monaco/` and `/healthz`. No WebSocket routes exist, so none are proxied.

## Headers sent upstream

`Host` (with port, so the backend's origin check sees the browser's origin), `X-Forwarded-For` (replaced
with the client address, never appended), `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Real-IP`, and
`X-Request-ID` (nginx's request id; the backend uses it in its logs and response, so one id traces a
request through both). The backend trusts these headers because its port is reachable only from the
proxy network (`FORWARDED_ALLOW_IPS=*`); the rate limiters therefore see real client addresses.

## Limits and timeouts

| Setting | Value | Why |
| --- | --- | --- |
| `client_max_body_size` | 8 MiB | outer cap; the backend answers above 6 MiB with its own JSON 413, the proxy above 8 MiB with the same JSON shape |
| client header / body timeout | 15 s / 30 s | slow-client protection |
| proxy connect timeout | 5 s | a dead upstream fails fast (JSON 503 `backend_unavailable` for the API) |
| read timeout `/api/` | 120 s | AI requests take up to 90 s |
| read timeout `/api/v1/agent/` | 300 s | agent runs take up to 240 s |
| read timeout frontend | 60 s | page rendering |

## Compression

gzip only for the frontend's text assets (`/_next/static`, `/monaco`, pages). API responses are not
compressed: they carry per-user data on a cookie-authenticated connection (BREACH-style attacks rely on
compressing secrets next to attacker-controlled input).

## Security headers

| Header | Set by | Value |
| --- | --- | --- |
| `Content-Security-Policy` (pages) | frontend (`frontend/proxy.ts`, `frontend/lib/csp.ts`), per request | see below |
| `Content-Security-Policy` (API) | backend | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'` |
| `X-Content-Type-Options` | frontend, backend | `nosniff` |
| `X-Frame-Options` | frontend, backend | `DENY` |
| `Referrer-Policy` | frontend / backend | `strict-origin-when-cross-origin` / `no-referrer` |
| `Permissions-Policy` | frontend, backend | camera, microphone, geolocation, payment disabled |
| `Cross-Origin-Opener-Policy` | frontend, backend | `same-origin` |
| `Strict-Transport-Security` | proxy in HTTPS mode (one header for every response) | `max-age=31536000; includeSubDomains` |
| `Cache-Control: no-store` | backend, every API response | per-user data |
| `Server` | proxy | `nginx` (no version: `server_tokens off`) |

### Content-Security-Policy for the application pages

```text
default-src 'self'; script-src 'self' 'nonce-<random per request>' 'strict-dynamic';
style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:;
worker-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self';
form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests (HTTPS only)
```

- **Scripts**: only Next.js scripts carrying the request's nonce run; `'strict-dynamic'` lets them load
  Next.js chunks and Monaco's loader and modules from `/monaco/vs`. No `'unsafe-inline'`, no
  `'unsafe-eval'` in production, no remote script origins. Pages are therefore rendered per request
  (a static page cannot carry a fresh nonce).
- **`style-src 'unsafe-inline'`**: Monaco inserts `<style>` elements and style attributes at run time,
  which nonces cannot cover. Styles cannot execute code.
- **`worker-src blob:`**: Monaco 0.57 starts each language worker from a small `blob:` bootstrap that
  loads the worker script from `/monaco/vs` (verified in its source: `URL.createObjectURL`).
- **`data:` images and fonts**: Monaco's stylesheets embed small icons.
- Development adds `'unsafe-eval'` (React's dev tooling) and the API origin to `connect-src`.

Verified in Chrome against the production-like stack: registration, projects, the editor (typing,
markers, workers), diagnostics, search and the agent panel ran with zero `securitypolicyviolation`
events, and an injected inline event handler was blocked (`script-src-attr`).

## HTTPS

Set `CODEWALK_PROXY_TLS=on` and provide, in `CODEWALK_TLS_DIR` (default `deploy/certs/`, git-ignored):

- `fullchain.pem`: the certificate chain;
- `privkey.pem`: the private key, readable by uid 101 (for example `chmod 640` and group 101, or `644`
  inside a directory only root can list).

The proxy refuses to start in TLS mode when either file is missing. Port 80 then redirects to HTTPS
and serves `/.well-known/acme-challenge/` from `CODEWALK_ACME_DIR`, so Let's Encrypt HTTP-01 works:

```bash
# first issuance (stack running with TLS off, or port 80 free), then renew from cron/systemd
certbot certonly --webroot -w /opt/codewalk/deploy/acme -d codewalk.example.com
cp /etc/letsencrypt/live/codewalk.example.com/{fullchain,privkey}.pem /opt/codewalk/deploy/certs/
docker compose -f docker-compose.prod.yml --env-file .env.production exec proxy nginx -s reload
```

TLS 1.2 and 1.3 only, server cipher preference off (modern clients choose), session tickets off,
HTTP/2 enabled. Set `CODEWALK_PUBLIC_ORIGIN=https://…`; production session cookies are always `Secure`.

**Behind a load balancer that terminates TLS** (cloud LB, Cloudflare, Traefik): keep
`CODEWALK_PROXY_TLS=off`, forward to port 80, and set `CODEWALK_PUBLIC_ORIGIN` to the public
`https://` origin so the backend accepts the browser's origin. HSTS then comes from the backend (API)
and should be enabled on the load balancer for pages.

No certificate is committed or generated by this repository. The infrastructure tests create a
throwaway self-signed certificate inside a disposable Docker volume only so `nginx -t` can parse the
HTTPS configuration; it is never stored on the host or used to serve traffic. Serving real HTTPS was
not exercised locally (no domain or certificate).

**Local development** needs no certificates: the dev stack and the local production-like run use plain
HTTP on `localhost`.
