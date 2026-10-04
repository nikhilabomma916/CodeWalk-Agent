# Deployment checklist

## First deployment

- [ ] Host: Docker Engine 25+ with Compose v2; ports 80/443 open; nothing else listening on them.
- [ ] DNS name points at the host.
- [ ] `.env.production` created from `.env.production.example`, `chmod 600`, not in git.
- [ ] `POSTGRES_PASSWORD` and `CODEWALK_SECRET_KEY` generated on the server (secrets.md), stored in the password manager / secret store.
- [ ] `CODEWALK_PUBLIC_ORIGIN=https://<host>`.
- [ ] TLS: `CODEWALK_PROXY_TLS=on` with `fullchain.pem` + `privkey.pem` in `CODEWALK_TLS_DIR` (readable by uid 101), **or** a TLS-terminating load balancer in front with `CODEWALK_PROXY_TLS=off`.
- [ ] Optional providers decided: keys set only if AI / semantic search should be available.
- [ ] `docker compose -f docker-compose.prod.yml --env-file .env.production config -q` passes.
- [ ] Docker log rotation configured (production-deployment.md).
- [ ] Backup schedule and off-host copy configured; one backup restored with `npm run db:restore` (verify mode).
- [ ] Firewall: only 80/443 reachable; PostgreSQL is not published by the compose file.

## Every release

- [ ] Release notes read: migrations? new variables?
- [ ] New variables added to `.env.production`.
- [ ] Backup taken and verified (runbook step 4).
- [ ] Images built or pulled for the release tag.
- [ ] `run --rm migrate` exited 0 **before** `up` (runbook step 6).
- [ ] `up -d --wait` exited 0; `ps` shows every service healthy, `migrate` Exited (0).
- [ ] `/api/v1/health/ready` → `"status":"ok"`, database `pass`.
- [ ] `npm run test:smoke` against the public URL passed.
- [ ] Logs checked for errors.
- [ ] Manual check: sign in, open a project, edit and save a file, diagnostics appear.
- [ ] Previous tag recorded for rollback.

## Security spot checks

- [ ] `curl -sI https://<host>/login` shows `content-security-policy` with a nonce, `strict-transport-security`, `x-frame-options: DENY`.
- [ ] `curl -s https://<host>/docs` → 404 (API docs off).
- [ ] Set-Cookie for the session has `HttpOnly; Secure; SameSite=lax`.
- [ ] `docker compose … ps` shows no published port except the proxy's.
