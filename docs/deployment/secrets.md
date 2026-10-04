# Secrets

## What is secret

| Secret | Used by | Where it lives |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | database, backend, migration job | `.env.production` on the server (or the platform's secret store) |
| `CODEWALK_SECRET_KEY` | backend start-up guard | same |
| `ANTHROPIC_API_KEY` / `CODEWALK_AI_API_KEY` (optional) | backend | same |
| `VOYAGE_API_KEY` (optional) | backend | same |
| TLS private key (`privkey.pem`) | proxy | `CODEWALK_TLS_DIR` on the server, read-only mount |
| Database backups | operators | off-host backup storage (they contain user data and password hashes) |

`CODEWALK_SECRET_KEY` is currently a required production guard and is not used to sign anything:
sessions are random 256-bit tokens of which only a SHA-256 hash is stored. It is reserved for future
signed tokens; rotating it today has no effect on existing sessions.

## Rules

- Never commit real values. Git ignores `.env`, `.env.*` (except the two `*.example` files), `*.pem`,
  `*.key`, `*.crt`, `deploy/certs/*`, `backups/` and `*.dump`. The example files hold placeholders only
  (`npm run test:infra` verifies this and that no such files are tracked).
- Never put a secret in a Dockerfile, a build argument, `docker-compose*.yml`, frontend code or any
  `NEXT_PUBLIC_*` variable. The images contain no secrets; everything arrives as runtime environment.
- Provider keys are backend-only. The frontend never sees them; the status endpoints report only
  whether a provider is configured.
- Do not paste secrets into source code, tests, issues, chat or logs. `docker compose config` without
  `-q` prints them: avoid it in shared terminals and CI logs.

## Generating

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"   # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                     # CODEWALK_SECRET_KEY
```

Generate on the server and write straight into `.env.production` (`chmod 600`, owned by the deploying
user). Keep a copy in your password manager or secret store, not in the repository.

## Local development

Put keys in the repository `.env` (git-ignored). `.env.example` shows the variable names with empty
values. Never ask anyone to paste a key into a source file.

## CI/CD (GitHub Actions)

- The required checks need no secrets: the backend job uses a throwaway CI-only database password,
  and the Docker job generates random stack secrets per run (`openssl rand`, masked with `::add-mask::`).
- Live provider tests run only on manual dispatch and read `ANTHROPIC_API_KEY` / `VOYAGE_API_KEY` from
  **repository or environment secrets** (Settings → Secrets and variables → Actions). They are passed
  as environment variables and are masked in logs.
- No image is pushed to a registry by CI. If you add a push step, use a registry token stored as a
  secret, never in the workflow file.

## Platform secret managers

If the host platform has a secret manager (for example Docker Swarm secrets, Kubernetes secrets, a
cloud provider's secret store, or systemd credentials), generate `.env.production` from it at deploy
time with permissions `600`, or inject the same variable names into the compose environment. The
application only reads environment variables; it needs no code change.

## Rotation

| Secret | How | Impact |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `docker compose … exec db psql -U codewalk -d postgres -c "ALTER ROLE codewalk PASSWORD '<new>'"` (run it interactively, not from a script that logs), update `.env.production`, then `up -d --wait` | backend and migrations reconnect with the new value; brief restart |
| Provider keys | revoke at the provider, set the new key, `up -d --wait backend` | AI requests fail until the backend restarts |
| `CODEWALK_SECRET_KEY` | set a new random value, restart the backend | none today (not used for signing) |
| TLS key | replace the files, `docker compose … exec proxy nginx -s reload` | none |

`POSTGRES_PASSWORD` in the environment only initialises a **new** database volume; for an existing
volume the password is changed with `ALTER ROLE` as above.

## If a secret leaks

Treat it as compromised: rotate it (table above), check the access logs, remove it from wherever it
leaked (and from git history if committed, which requires coordinating a history rewrite with the
team). Module 14's runner incident (security-validation.md, F3) is an example.
