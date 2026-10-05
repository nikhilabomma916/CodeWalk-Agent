"""GitHub integration endpoints (Module 20). Every endpoint acts for the signed-in user only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUserDep, FileServiceDep, SessionDep, SettingsDep
from app.core.exceptions import AppError
from app.schemas.github import (
    GitHubBranchPage,
    GitHubConnectResponse,
    GitHubImportRequest,
    GitHubImportResult,
    GitHubRepositoryPage,
    GitHubStatus,
    OwnerName,
    RepositoryName,
)
from app.services.github.service import STATE_COOKIE, STATE_TTL_SECONDS, GitHubService

router = APIRouter(prefix="/github", tags=["github"])

CALLBACK_PATH = "/api/v1/github/callback"
# Outcomes reported to the frontend after the callback; never GitHub's own text.
CALLBACK_RESULTS = frozenset(
    {"connected", "github_oauth_state_invalid", "github_oauth_failed", "github_unavailable", "github_error"}
)


def get_github_service(
    request: Request, session: SessionDep, settings: SettingsDep, user: CurrentUserDep
) -> GitHubService:
    return GitHubService(
        session, settings, user, request.app.state.github_client, request.app.state.github_import_limiter
    )


GitHubServiceDep = Annotated[GitHubService, Depends(get_github_service)]


@router.get("/status", response_model=GitHubStatus, summary="GitHub integration and connection state")
def github_status(service: GitHubServiceDep) -> GitHubStatus:
    return service.status()


@router.post(
    "/connect",
    response_model=GitHubConnectResponse,
    summary="Start connecting a GitHub account",
    description=(
        "Returns GitHub's authorization URL (the browser navigates there) and sets a short-lived, "
        "signed, HttpOnly state cookie that the callback checks."
    ),
)
def github_connect(
    service: GitHubServiceDep, settings: SettingsDep, response: Response
) -> GitHubConnectResponse:
    start = service.start_connect()
    response.set_cookie(
        STATE_COOKIE,
        start.cookie_value,
        max_age=STATE_TTL_SECONDS,
        path=CALLBACK_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return GitHubConnectResponse(authorize_url=start.authorize_url)


@router.get("/callback", include_in_schema=False)
def github_callback(
    request: Request,
    service: GitHubServiceDep,
    settings: SettingsDep,
    code: Annotated[str | None, Query(max_length=200)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """GitHub sends the browser here. Redirects to the frontend with a fixed result code."""
    result = "connected"
    try:
        service.finish_connect(code=code, state=state, cookie=request.cookies.get(STATE_COOKIE))
    except AppError as exc:
        result = exc.code if exc.code in CALLBACK_RESULTS else "github_error"
    target = f"{settings.post_oauth_url}/app/uploads?github={result}"
    redirect = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(
        STATE_COOKIE, path=CALLBACK_PATH, httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    return redirect


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect GitHub")
def github_disconnect(service: GitHubServiceDep) -> Response:
    """Revokes CodeWalk's authorization at GitHub (best effort) and deletes the stored token."""
    service.disconnect()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/repositories", response_model=GitHubRepositoryPage, summary="Repositories the connection can read"
)
def github_repositories(
    service: GitHubServiceDep, page: Annotated[int, Query(ge=1, le=100)] = 1
) -> GitHubRepositoryPage:
    return service.repositories(page)


@router.get(
    "/repositories/{owner}/{repository}/branches",
    response_model=GitHubBranchPage,
    summary="Branches of a repository",
)
def github_branches(
    owner: OwnerName,
    repository: RepositoryName,
    service: GitHubServiceDep,
    page: Annotated[int, Query(ge=1, le=100)] = 1,
) -> GitHubBranchPage:
    return service.branches(owner, repository, page)


@router.post(
    "/import",
    response_model=GitHubImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import a repository branch as a new project",
    description=(
        "Downloads the branch's current commit (size-limited), stores its text files through the "
        "regular checked file import as an Uploads project (credentials files, dependency folders, "
        "binaries, links and oversized files are skipped and listed), and runs project intelligence."
    ),
)
def github_import(
    data: GitHubImportRequest, service: GitHubServiceDep, files: FileServiceDep
) -> GitHubImportResult:
    service.files = files
    return service.import_repository(data)
