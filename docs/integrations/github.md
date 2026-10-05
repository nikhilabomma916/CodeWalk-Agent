# GitHub integration (Module 20)

Users connect their GitHub account with OAuth and import a repository branch as a project. An
imported repository becomes an **Uploads** project (analyzed read-only; the agent never changes it),
with its repository, branch and commit recorded for later updates.

## Setup

1. Create a GitHub **OAuth App** (GitHub → Settings → Developer settings → OAuth Apps).
   *Authorization callback URL*: `<API origin>/api/v1/github/callback`
   (`http://localhost:8000/api/v1/github/callback` locally; `https://<domain>/api/v1/github/callback`
   on a same-origin deployment).
2. Set on the backend (never in `NEXT_PUBLIC_*`):

| Variable | Purpose |
| --- | --- |
| `CODEWALK_GITHUB_CLIENT_ID` | OAuth app client id |
| `CODEWALK_GITHUB_CLIENT_SECRET` | OAuth app client secret (secret) |
| `CODEWALK_GITHUB_CALLBACK_URL` | exactly the callback URL registered above (https in production) |
| `CODEWALK_TOKEN_ENCRYPTION_KEY` | 32 random bytes, base64 (secret); encrypts stored tokens |
| `CODEWALK_GITHUB_SCOPES` | empty (default): public repositories only; `repo`: private ones too |
| `CODEWALK_APP_URL` | frontend URL to return to after connecting (default: first CORS origin, else same origin) |

The integration is off (the Uploads page shows no GitHub section) unless the first four are set.
Generate a key: `python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`.

**Scopes.** GitHub OAuth apps have no read-only scope for private repositories: `repo` grants read
*and write* access to the user's repositories. CodeWalk only ever reads (and revokes its own grant on
disconnect), but the token could write if it leaked; that is why the default is public-only. Write
and admin scopes are refused by configuration validation.

## Security

- **OAuth state**: a random state plus a signed (HMAC), 10-minute, HttpOnly, SameSite=Lax cookie
  scoped to the callback path, bound to the signed-in user, checked in constant time and cleared after
  one use. A state started by another user, a missing or expired cookie, or a forged state fails.
- **Callback**: the code is exchanged server-side with the client secret; the browser is redirected
  to a fixed frontend path with a fixed result code (no GitHub text, no open redirect).
- **Token at rest**: AES-256-GCM, random nonce, associated data = the user id (a value copied to
  another user's row does not decrypt). Never returned by the API, logged, put in prompts or RAG.
  httpx request logging stays at WARNING because archive redirects carry a short-lived token.
- **Key rotation**: set the new key as `CODEWALK_TOKEN_ENCRYPTION_KEY` and the old one in
  `CODEWALK_TOKEN_ENCRYPTION_OLD_KEYS`; tokens are re-encrypted with the new key on next use. A token
  that cannot be decrypted (key lost) is treated as disconnected: the user connects again.
- **Disconnect** revokes CodeWalk's grant at GitHub (best effort) and deletes the stored token. A token
  GitHub no longer accepts is deleted, and the user is asked to reconnect.
- **Isolation**: one connection per user; every endpoint acts for the signed-in user; imported
  projects are owned by the importer.

## Import

`POST /api/v1/github/import {owner, repository, branch, project_name?}`:

1. Owner, repository and branch names are validated; the branch's current commit is resolved.
2. Duplicate check: the same repository branch already imported by this user → 409.
3. The archive at that commit is downloaded with a cap (`CODEWALK_GITHUB_MAX_ARCHIVE_BYTES`, 50 MiB)
   and read **in memory**: only regular files are read (links, devices: skipped; nothing is written
   to disk), dependency/build folders and credentials files are skipped without being read, binary
   and non-UTF-8 files are skipped, per-file limit `CODEWALK_MAX_SOURCE_BYTES`, file limit
   `CODEWALK_SCAN_MAX_FILES`, total text limit `CODEWALK_GITHUB_MAX_REPOSITORY_BYTES` (100 MiB) and
   a time limit (`CODEWALK_GITHUB_TIMEOUT_SECONDS`, 120 s). Oversized repositories are refused before
   any project is created.
4. Files are stored through the regular file import (path validation, credentials, ignored folders,
   size, duplicates), preserving the folder structure; then project intelligence indexes the project.
   Semantic (RAG) indexing is started from the project as for any other project; credentials files
   are never stored, so they never reach AI or embedding providers.
5. The response lists imported and skipped files (with reasons) and the indexing outcome.

Imports run within the request (there is no background worker); the limits keep them within the
platform's request time. Rate limit: `CODEWALK_GITHUB_IMPORT_MAX_RUNS` per
`CODEWALK_GITHUB_IMPORT_WINDOW_SECONDS` per user (default 10 per hour).

## Not implemented (prepared for)

`project_sources` keeps repository id, branch and commit so pulling updates, comparing with the
repository, commits and pull requests can be added later. None of these write operations exist now.

## Tests

`tests/test_github_units.py` (encryption, rotation, settings, validation, archive reader) and
`tests/db/test_github_api.py` (OAuth flow and state attacks, cross-user isolation, import, unsafe
files, duplicates, oversized repositories, rate limit, disconnect/revocation, revoked tokens, key
change, token leakage) run against a fake GitHub behind the real client. No real GitHub OAuth app or
account has been used; validate once with a real OAuth app before launch.
