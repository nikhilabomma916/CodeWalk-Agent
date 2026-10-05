"""Minimal GitHub REST and OAuth client (Module 20). Read-only apart from revoking its own grant.

Tokens are sent only in the Authorization header (never in a URL) and are never logged; httpx's own
request logging is kept at WARNING (app.core.logging) because archive redirects carry a short-lived
download token in their query string. Failures become ``GitHubError`` subclasses with client-safe
messages; GitHub's response bodies are never passed through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"
OAUTH_URL = "https://github.com"
API_VERSION = "2022-11-28"


class GitHubError(AppError):
    status_code = 502
    code = "github_error"


class GitHubUnavailableError(GitHubError):
    status_code = 503
    code = "github_unavailable"

    def __init__(self, message: str = "GitHub could not be reached. Try again shortly.") -> None:
        super().__init__(message)


class GitHubAuthorizationError(GitHubError):
    """The stored token no longer works (revoked, expired, or the app was uninstalled)."""

    status_code = 409
    code = "github_reauthorization_required"

    def __init__(self) -> None:
        super().__init__("GitHub no longer accepts this connection. Connect your GitHub account again.")


class GitHubRateLimitedError(GitHubError):
    status_code = 429
    code = "github_rate_limited"

    def __init__(self) -> None:
        super().__init__("GitHub's rate limit was reached. Try again later.")


class GitHubNotFoundError(GitHubError):
    status_code = 404
    code = "github_not_found"


class GitHubArchiveTooLargeError(GitHubError):
    status_code = 413
    code = "github_repository_too_large"


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    scopes: list[str]


class GitHubClient:
    def __init__(self, *, timeout_seconds: float, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            transport=transport,
            headers={"User-Agent": "CodeWalk-Agent", "X-GitHub-Api-Version": API_VERSION},
        )

    def close(self) -> None:
        self._http.close()

    # --- OAuth ---------------------------------------------------------------------------------

    @staticmethod
    def authorize_url(*, client_id: str, callback_url: str, scopes: list[str], state: str) -> str:
        query = {
            "client_id": client_id,
            "redirect_uri": callback_url,
            "state": state,
            "allow_signup": "false",
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        return f"{OAUTH_URL}/login/oauth/authorize?{urlencode(query)}"

    def exchange_code(
        self, *, client_id: str, client_secret: str, code: str, callback_url: str
    ) -> OAuthToken:
        response = self._send(
            "POST",
            f"{OAUTH_URL}/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": callback_url,
            },
            headers={"Accept": "application/json"},
        )
        body = self._json(response)
        token = body.get("access_token") if isinstance(body, dict) else None
        if response.status_code != 200 or not isinstance(token, str) or not token:
            # e.g. bad_verification_code (expired, reused or forged code); GitHub's text is not shown.
            error = body.get("error") if isinstance(body, dict) else None
            logger.warning(
                "GitHub OAuth code exchange failed (%s)", error if isinstance(error, str) else "unknown"
            )
            raise GitHubError(
                "GitHub did not accept the authorization. Try connecting again.", code="github_oauth_failed"
            )
        scope = body.get("scope")
        return OAuthToken(
            token, sorted(s for s in (scope or "").split(",") if s) if isinstance(scope, str) else []
        )

    def revoke(self, *, client_id: str, client_secret: str, token: str) -> None:
        """Deletes CodeWalk's authorization for the account at GitHub (best effort)."""
        response = self._send(
            "DELETE",
            f"{API_URL}/applications/{quote(client_id, safe='')}/grant",
            auth=(client_id, client_secret),
            json={"access_token": token},
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code not in (204, 404, 422):
            logger.warning("GitHub grant revocation returned %s", response.status_code)

    # --- REST ----------------------------------------------------------------------------------

    def get_user(self, token: str) -> dict[str, Any]:
        return self._get_object(token, "/user")

    def list_repositories(self, token: str, *, page: int) -> list[dict[str, Any]]:
        params = {
            "per_page": 100,
            "page": page,
            "sort": "updated",
            "affiliation": "owner,collaborator,organization_member",
        }
        data = self._json(self._api(token, "GET", "/user/repos", params=params))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def get_repository(self, token: str, owner: str, repo: str) -> dict[str, Any]:
        return self._get_object(token, f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}")

    def list_branches(self, token: str, owner: str, repo: str, *, page: int) -> list[dict[str, Any]]:
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/branches"
        data = self._json(self._api(token, "GET", path, params={"per_page": 100, "page": page}))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def get_branch(self, token: str, owner: str, repo: str, branch: str) -> dict[str, Any]:
        return self._get_object(
            token, f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/branches/{quote(branch, safe='')}"
        )

    def download_archive(
        self, token: str, owner: str, repo: str, commit_sha: str, *, max_bytes: int
    ) -> bytes:
        """The repository at ``commit_sha`` as ``.tar.gz``, refused once it exceeds ``max_bytes``."""
        repository = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
        url = f"{API_URL}/repos/{repository}/tarball/{quote(commit_sha, safe='')}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            # GitHub answers with a redirect to codeload.github.com; httpx drops the Authorization
            # header when the redirect leaves api.github.com, which the download does not need.
            with self._http.stream("GET", url, headers=headers, follow_redirects=True) as response:
                self._check(response)
                declared = response.headers.get("content-length")
                if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                    raise GitHubArchiveTooLargeError(
                        "The repository archive is larger than the import limit."
                    )
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > max_bytes:
                        raise GitHubArchiveTooLargeError(
                            "The repository archive is larger than the import limit."
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException:
            raise GitHubUnavailableError("GitHub did not send the repository in time.") from None
        except httpx.HTTPError:
            raise GitHubUnavailableError() from None

    # --- plumbing ------------------------------------------------------------------------------

    def _get_object(self, token: str, path: str) -> dict[str, Any]:
        data = self._json(self._api(token, "GET", path))
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected answer.")
        return data

    def _api(self, token: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        response = self._send(method, f"{API_URL}{path}", headers=headers, **kwargs)
        self._check(response)
        return response

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise GitHubUnavailableError("GitHub did not answer in time.") from None
        except httpx.HTTPError:
            raise GitHubUnavailableError() from None

    @staticmethod
    def _check(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            raise GitHubAuthorizationError()
        if status in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
            or status == 429
        ):
            raise GitHubRateLimitedError()
        if status in (403, 404):
            # GitHub answers 404 for private repositories the token cannot see.
            raise GitHubNotFoundError(
                "The repository or branch was not found, or this connection cannot access it."
            )
        if status >= 500:
            raise GitHubUnavailableError()
        raise GitHubError("GitHub rejected the request.")

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise GitHubError("GitHub returned an unexpected answer.") from None
