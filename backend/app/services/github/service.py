"""GitHub account connection and repository import (Module 20).

OAuth (authorization code flow, GitHub OAuth app):

1. ``start_connect`` makes a random state, returns GitHub's authorize URL, and a signed state cookie
   bound to the signed-in user (HMAC, 10 minutes, HttpOnly, SameSite=Lax, path = the callback).
2. GitHub redirects the browser to the callback with ``code`` and ``state``. ``finish_connect``
   requires the same signed-in user, a valid unexpired cookie, and a matching state (constant-time),
   exchanges the code server-side with the client secret, and stores the token only encrypted.
   The cookie is cleared whatever the outcome, so a state works once.

Import: the repository's archive at the branch's current commit is downloaded with a size cap, read
in memory (archive.py), and stored through the regular, fully checked file import as an ``upload``
project (Uploads area, analyzed read-only), then indexed by project intelligence. The token stays in
this module: it is never returned, logged, or given to AI or retrieval, and credentials files in the
repository are never stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import TokenCipher, TokenDecryptionError
from app.core.exceptions import AppError, ConflictError
from app.core.rate_limit import AttemptLimiter
from app.db.models import ActivityType, GitHubConnection, Project, ProjectSource, User
from app.schemas.github import (
    GitHubBranchPage,
    GitHubImportRequest,
    GitHubImportResult,
    GitHubImportSkipped,
    GitHubRepository,
    GitHubRepositoryPage,
    GitHubStatus,
)
from app.schemas.projects import FileImportItem, ProjectCreate
from app.services.activity import ActivityRecorder
from app.services.files import FileService
from app.services.github.archive import (
    ArchiveInvalidError,
    ArchiveTimeoutError,
    ArchiveTooLargeError,
    read_archive,
)
from app.services.github.client import (
    GitHubArchiveTooLargeError,
    GitHubAuthorizationError,
    GitHubClient,
    GitHubError,
    GitHubUnavailableError,
)
from app.services.project_intelligence.service import ProjectIntelligenceService
from app.services.projects import ProjectService

logger = logging.getLogger(__name__)

STATE_COOKIE = "codewalk_github_state"
STATE_TTL_SECONDS = 600
IMPORT_BATCH = 100
MAX_SKIPPED_LISTED = 200


class GitHubNotConfiguredError(AppError):
    status_code = 503
    code = "github_not_configured"

    def __init__(self) -> None:
        super().__init__("GitHub integration is not configured on this server.")


class GitHubNotConnectedError(AppError):
    status_code = 409
    code = "github_not_connected"

    def __init__(self) -> None:
        super().__init__("Connect your GitHub account first.")


class GitHubImportLimitError(AppError):
    status_code = 429
    code = "github_import_rate_limited"


@dataclass(frozen=True)
class ConnectStart:
    authorize_url: str
    cookie_value: str


class GitHubService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        user: User,
        client: GitHubClient,
        import_limiter: AttemptLimiter,
        files: FileService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.user = user
        self.client = client
        self.import_limiter = import_limiter
        self.files = files
        self.cipher = TokenCipher.from_settings(settings)

    # --- status and connection ---------------------------------------------------------------

    def status(self) -> GitHubStatus:
        connection = self._connection()
        return GitHubStatus(
            configured=self.settings.github_configured,
            connected=connection is not None,
            login=connection.github_login if connection else None,
            scopes=connection.scopes.split() if connection and connection.scopes else [],
            private_repositories="repo" in self.settings.github_scopes,
            connected_at=connection.created_at if connection else None,
        )

    def start_connect(self) -> ConnectStart:
        self._require_configured()
        state = secrets.token_urlsafe(32)
        expires = int(time.time()) + STATE_TTL_SECONDS
        payload = _b64(json.dumps({"u": str(self.user.id), "s": state, "e": expires}, separators=(",", ":")))
        cookie = f"{payload}.{self._sign(payload)}"
        url = self.client.authorize_url(
            client_id=self.settings.github_client_id or "",
            callback_url=self.settings.github_callback_url or "",
            scopes=self.settings.github_scopes,
            state=state,
        )
        return ConnectStart(authorize_url=url, cookie_value=cookie)

    def finish_connect(self, *, code: str | None, state: str | None, cookie: str | None) -> None:
        """Raises ``GitHubError(code="github_oauth_state_invalid")`` unless the state checks out."""
        self._require_configured()
        if not self._state_matches(state, cookie):
            logger.warning("GitHub OAuth callback with an invalid or expired state (user %s)", self.user.id)
            raise GitHubError(
                "The GitHub authorization expired or was not started here. Try again.",
                code="github_oauth_state_invalid",
                status_code=400,
            )
        if not code or len(code) > 200:
            raise GitHubError(
                "GitHub did not return an authorization code.", code="github_oauth_failed", status_code=400
            )
        token = self.client.exchange_code(
            client_id=self.settings.github_client_id or "",
            client_secret=self._client_secret(),
            code=code,
            callback_url=self.settings.github_callback_url or "",
        )
        account = self.client.get_user(token.access_token)
        github_id, login = account.get("id"), account.get("login")
        if not isinstance(github_id, int) or not isinstance(login, str) or not login:
            raise GitHubError("GitHub returned an unexpected account.")
        connection = self._connection()
        ciphertext = self._encrypt(token.access_token)
        if connection is None:
            connection = GitHubConnection(
                user_id=self.user.id,
                github_user_id=github_id,
                github_login=login[:39],
                scopes=" ".join(token.scopes),
                token_ciphertext=ciphertext,
            )
            self.session.add(connection)
        else:  # reconnecting replaces the stored token
            connection.github_user_id = github_id
            connection.github_login = login[:39]
            connection.scopes = " ".join(token.scopes)
            connection.token_ciphertext = ciphertext
        self.session.commit()
        logger.info("GitHub account connected (user %s, GitHub login %s)", self.user.id, login)

    def disconnect(self) -> None:
        """Revokes CodeWalk's grant at GitHub (best effort) and deletes the stored token."""
        connection = self._connection()
        if connection is None:
            return
        if self.settings.github_configured:
            try:
                token = self._decrypt(connection)
                self.client.revoke(
                    client_id=self.settings.github_client_id or "",
                    client_secret=self._client_secret(),
                    token=token,
                )
            except (TokenDecryptionError, GitHubError):
                logger.warning(
                    "GitHub grant could not be revoked for user %s; the token is deleted anyway", self.user.id
                )
        self.session.delete(connection)
        self.session.commit()
        logger.info("GitHub account disconnected (user %s)", self.user.id)

    # --- browsing ------------------------------------------------------------------------------

    def repositories(self, page: int) -> GitHubRepositoryPage:
        items = self._with_token(lambda token: self.client.list_repositories(token, page=page))
        repositories = [repo for repo in (_repository(item) for item in items) if repo is not None]
        return GitHubRepositoryPage(items=repositories, page=page, has_more=len(items) == 100)

    def branches(self, owner: str, repository: str, page: int) -> GitHubBranchPage:
        items = self._with_token(lambda token: self.client.list_branches(token, owner, repository, page=page))
        names = [item["name"] for item in items if isinstance(item.get("name"), str)]
        return GitHubBranchPage(items=names, page=page, has_more=len(items) == 100)

    # --- import --------------------------------------------------------------------------------

    def import_repository(self, request: GitHubImportRequest) -> GitHubImportResult:
        if self.files is None:  # pragma: no cover - wired by the route
            raise RuntimeError("GitHubService.import_repository needs a FileService")
        self._require_configured()
        if (retry_after := self.import_limiter.acquire(f"github-import:{self.user.id}")) is not None:
            error = GitHubImportLimitError("Too many repository imports. Try again later.")
            error.headers = {"Retry-After": str(retry_after)}
            raise error
        deadline = time.monotonic() + self.settings.github_timeout_seconds
        owner, name, branch = request.owner, request.repository, request.branch

        def fetch(token: str) -> tuple[dict[str, object], str, bytes]:
            repo = self.client.get_repository(token, owner, name)
            head = self.client.get_branch(token, owner, name, branch)
            commit = head.get("commit")
            sha = commit.get("sha") if isinstance(commit, dict) else None
            if not isinstance(sha, str) or len(sha) != 40:
                raise GitHubError("GitHub returned an unexpected branch.")
            self._refuse_duplicate(repo.get("id"), branch)
            archive = self.client.download_archive(
                token, owner, name, sha, max_bytes=self.settings.github_max_archive_bytes
            )
            return repo, sha, archive

        repo, sha, archive = self._with_token(fetch)
        repo_id = repo.get("id")
        if not isinstance(repo_id, int):
            raise GitHubError("GitHub returned an unexpected repository.")
        try:
            contents = read_archive(
                archive,
                max_file_bytes=self.settings.max_source_bytes,
                max_files=self.settings.scan_max_files,
                max_total_bytes=self.settings.github_max_repository_bytes,
                deadline=deadline,
            )
        except ArchiveTooLargeError as exc:
            raise GitHubArchiveTooLargeError(str(exc)) from None
        except ArchiveTimeoutError:
            raise GitHubUnavailableError("Reading the repository took too long.") from None
        except ArchiveInvalidError:
            raise GitHubError("The repository archive could not be read.") from None
        del archive

        projects = ProjectService(self.session, self.settings, self.user)
        project = projects.create(
            ProjectCreate(
                name=request.project_name or name,
                description=f"Imported from GitHub: {owner}/{name} ({branch} @ {sha[:7]})",
                origin="upload",
            )
        )
        full_name = repo.get("full_name") if isinstance(repo.get("full_name"), str) else f"{owner}/{name}"
        source = ProjectSource(
            project_id=project.id,
            repository_id=repo_id,
            full_name=str(full_name)[:140],
            branch=branch,
            commit_sha=sha,
            is_private=bool(repo.get("private")),
        )
        self.session.add(source)
        self.session.commit()

        skipped = [GitHubImportSkipped(path=path, reason=reason) for path, reason in contents.skipped]
        imported = 0
        for start in range(0, len(contents.files), IMPORT_BATCH):
            batch = [
                FileImportItem(path=path, content=text)
                for path, text in contents.files[start : start + IMPORT_BATCH]
            ]
            created, refused = self.files.import_files(project.id, batch)
            imported += len(created)
            skipped.extend(GitHubImportSkipped(path=item.path, reason=item.reason) for item in refused)
        contents.files.clear()

        source.files_imported = imported
        source.files_skipped = len(skipped)
        ActivityRecorder(self.session, self.user).record(
            ActivityType.GITHUB_IMPORTED,
            project,
            details={
                "repository": source.full_name,
                "branch": branch,
                "commit": sha,
                "files": imported,
                "skipped": len(skipped),
            },
        )
        self.session.commit()

        indexing, indexed = "completed", 0
        try:
            indexed = len(
                ProjectIntelligenceService(self.session, self.settings, self.user).analyze(project.id).files
            )
        except Exception:  # the files are imported; indexing can be run again from the project
            self.session.rollback()
            logger.exception("Project intelligence failed after a GitHub import (project %s)", project.id)
            indexing = "failed"
        logger.info(
            "GitHub repository imported (user %s, project %s, %s files)", self.user.id, project.id, imported
        )
        return GitHubImportResult(
            project_id=project.id,
            project_name=project.name,
            repository=source.full_name,
            branch=branch,
            commit_sha=sha,
            files_imported=imported,
            files_skipped=len(skipped),
            skipped_by_reason=dict(Counter(item.reason for item in skipped)),
            skipped=skipped[:MAX_SKIPPED_LISTED],
            indexing=indexing,
            indexed_files=indexed,
        )

    def source_of(self, project: Project) -> ProjectSource | None:
        return self.session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == project.id)
        ).first()

    # --- internals -----------------------------------------------------------------------------

    def _require_configured(self) -> None:
        if not self.settings.github_configured or self.cipher is None:
            raise GitHubNotConfiguredError()

    def _client_secret(self) -> str:
        secret = self.settings.github_client_secret
        return secret.get_secret_value() if secret else ""

    def _connection(self) -> GitHubConnection | None:
        return self.session.scalars(
            select(GitHubConnection).where(GitHubConnection.user_id == self.user.id)
        ).first()

    def _with_token[T](self, call: Callable[[str], T]) -> T:
        self._require_configured()
        connection = self._connection()
        if connection is None:
            raise GitHubNotConnectedError()
        try:
            token = self._decrypt(connection)
        except TokenDecryptionError:
            logger.warning("Stored GitHub token for user %s could not be decrypted", self.user.id)
            raise GitHubAuthorizationError() from None
        try:
            result = call(token)
        except GitHubAuthorizationError:
            # The grant was revoked at GitHub: forget the dead token so the user can reconnect.
            self.session.delete(connection)
            self.session.commit()
            raise
        if self.cipher is not None and self.cipher.needs_rotation(connection.token_ciphertext):
            connection.token_ciphertext = self._encrypt(
                token
            )  # key rotation: re-encrypt with the current key
        connection.last_used_at = datetime.now(UTC)
        self.session.commit()
        return result

    def _refuse_duplicate(self, repository_id: object, branch: str) -> None:
        existing = self.session.scalars(
            select(ProjectSource)
            .join(Project, Project.id == ProjectSource.project_id)
            .where(
                Project.owner_id == self.user.id,
                ProjectSource.repository_id == repository_id,
                ProjectSource.branch == branch,
            )
        ).first()
        if existing is not None:
            raise ConflictError(
                "This repository branch is already imported as one of your projects.",
                code="github_repository_already_imported",
            )

    def _associated_data(self) -> str:
        return f"github-token:{self.user.id}"

    def _encrypt(self, token: str) -> str:
        if self.cipher is None:
            raise GitHubNotConfiguredError()
        return self.cipher.encrypt(token, associated_data=self._associated_data())

    def _decrypt(self, connection: GitHubConnection) -> str:
        if self.cipher is None:
            raise TokenDecryptionError()
        return self.cipher.decrypt(connection.token_ciphertext, associated_data=self._associated_data())

    def _signing_key(self) -> bytes:
        key = self.settings.token_encryption_key
        material = key.get_secret_value() if key else ""
        return hashlib.sha256(b"codewalk-github-oauth-state:" + material.encode()).digest()

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._signing_key(), payload.encode(), hashlib.sha256).digest())

    def _state_matches(self, state: str | None, cookie: str | None) -> bool:
        if not state or not cookie or len(cookie) > 1000 or "." not in cookie:
            return False
        payload, signature = cookie.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(payload)):
            return False
        try:
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        return (
            data.get("u") == str(self.user.id)
            and isinstance(data.get("e"), int)
            and data["e"] >= int(time.time())
            and isinstance(data.get("s"), str)
            and hmac.compare_digest(data["s"], state)
        )


def _b64(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _repository(item: dict[str, object]) -> GitHubRepository | None:
    """The fields CodeWalk shows; anything malformed is left out."""
    owner = item.get("owner")
    description = item.get("description")
    size = item.get("size")
    updated = item.get("updated_at")
    try:
        return GitHubRepository.model_validate(
            {
                "id": item.get("id"),
                "full_name": item.get("full_name"),
                "owner": owner.get("login") if isinstance(owner, dict) else None,
                "name": item.get("name"),
                "private": bool(item.get("private")),
                "default_branch": item.get("default_branch") or "main",
                "description": description[:300] if isinstance(description, str) and description else None,
                "size_kb": size if isinstance(size, int) else 0,
                "updated_at": updated if isinstance(updated, str) else None,
            }
        )
    except ValueError:
        return None
