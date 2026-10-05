"""Module 20 units: token encryption, GitHub settings, request validation, and the archive reader."""

from __future__ import annotations

import base64
import io
import os
import tarfile
import time

import pytest
from pydantic import ValidationError

from app.core.crypto import TokenCipher, TokenDecryptionError
from app.schemas.github import GitHubImportRequest
from app.services.github.archive import (
    ArchiveInvalidError,
    ArchiveTimeoutError,
    ArchiveTooLargeError,
    read_archive,
)
from app.services.github.client import GitHubClient
from tests.conftest import make_settings

TOKEN = "gho_" + "t" * 36


def new_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


# --- token encryption -----------------------------------------------------------------------------


def test_tokens_round_trip_and_are_bound_to_their_owner() -> None:
    cipher = TokenCipher.from_settings(make_settings(token_encryption_key=new_key()))
    assert cipher is not None
    stored = cipher.encrypt(TOKEN, associated_data="github-token:user-a")
    assert TOKEN not in stored
    assert stored.startswith("v1.")
    assert cipher.decrypt(stored, associated_data="github-token:user-a") == TOKEN
    assert cipher.encrypt(TOKEN, associated_data="github-token:user-a") != stored  # fresh nonce each time
    with pytest.raises(TokenDecryptionError):  # copied to another user's row
        cipher.decrypt(stored, associated_data="github-token:user-b")


@pytest.mark.parametrize("damage", ["flip", "truncate", "garbage", "version"])
def test_tampered_values_do_not_decrypt(damage: str) -> None:
    cipher = TokenCipher.from_settings(make_settings(token_encryption_key=new_key()))
    assert cipher is not None
    stored = cipher.encrypt(TOKEN, associated_data="a")
    damaged = {
        "flip": stored[:-2] + ("A" if stored[-2] != "A" else "B") + stored[-1],
        "truncate": stored[:-10],
        "garbage": "not-a-token",
        "version": "v2" + stored[2:],
    }[damage]
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(damaged, associated_data="a")


def test_key_rotation_keeps_old_values_readable_and_flags_them() -> None:
    old, new = new_key(), new_key()
    before = TokenCipher.from_settings(make_settings(token_encryption_key=old))
    assert before is not None
    stored = before.encrypt(TOKEN, associated_data="a")
    after = TokenCipher.from_settings(make_settings(token_encryption_key=new, token_encryption_old_keys=old))
    assert after is not None
    assert after.decrypt(stored, associated_data="a") == TOKEN
    assert after.needs_rotation(stored)
    assert not after.needs_rotation(after.encrypt(TOKEN, associated_data="a"))
    without_old = TokenCipher.from_settings(make_settings(token_encryption_key=new))
    assert without_old is not None
    with pytest.raises(TokenDecryptionError):
        without_old.decrypt(stored, associated_data="a")


@pytest.mark.parametrize("key", ["short", base64.b64encode(os.urandom(16)).decode(), "not base64 !!"])
def test_weak_or_malformed_keys_are_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="CODEWALK_TOKEN_ENCRYPTION_KEY"):
        make_settings(token_encryption_key=key)


def test_standard_base64_keys_are_accepted() -> None:
    assert make_settings(token_encryption_key=base64.b64encode(os.urandom(32)).decode()).token_encryption_key


# --- settings -------------------------------------------------------------------------------------


def configured(**extra: object) -> dict[str, object]:
    return {
        "github_client_id": "Iv1.abc123",
        "github_client_secret": "secret-value",
        "github_callback_url": "http://localhost:8000/api/v1/github/callback",
        "token_encryption_key": new_key(),
        **extra,
    }


def test_github_is_configured_only_with_every_part() -> None:
    assert make_settings(**configured()).github_configured
    for missing in (
        "github_client_id",
        "github_client_secret",
        "github_callback_url",
        "token_encryption_key",
    ):
        assert not make_settings(**configured(**{missing: ""})).github_configured


@pytest.mark.parametrize("scopes", ["delete_repo", "repo admin:org", "write:packages", "workflow"])
def test_only_read_scopes_can_be_requested(scopes: str) -> None:
    with pytest.raises(ValidationError, match="CODEWALK_GITHUB_SCOPES"):
        make_settings(github_scopes=scopes)


def test_default_scope_is_public_repositories_only() -> None:
    assert make_settings().github_scopes == []
    assert make_settings(github_scopes="repo, read:user").github_scopes == ["read:user", "repo"]


def test_production_requires_https_callback_and_app_urls() -> None:
    production = {"env": "production", "secret_key": "k" * 48, "cors_origins": []}
    with pytest.raises(ValidationError, match="CODEWALK_GITHUB_CALLBACK_URL must use https"):
        make_settings(**configured(**production))
    with pytest.raises(ValidationError, match="plain http"):
        make_settings(github_callback_url="https://user:pw@codewalk.example/api/v1/github/callback")
    make_settings(
        **configured(github_callback_url="https://codewalk.example/api/v1/github/callback", **production)
    )


def test_post_oauth_redirect_goes_to_the_frontend() -> None:
    assert make_settings().post_oauth_url == "http://localhost:3000"  # first allowed origin
    assert make_settings(cors_origins=[]).post_oauth_url == ""  # same origin
    assert make_settings(app_url="https://app.example/").post_oauth_url == "https://app.example"


def test_authorize_url_carries_state_and_scope_but_no_secret() -> None:
    url = GitHubClient.authorize_url(
        client_id="Iv1.abc", callback_url="https://x.example/cb", scopes=["repo"], state="st4te"
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "state=st4te" in url
    assert "scope=repo" in url
    assert "secret" not in url
    assert "scope=" not in GitHubClient.authorize_url(
        client_id="i", callback_url="https://x/cb", scopes=[], state="s"
    )


# --- request validation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"owner": "-bad", "repository": "r", "branch": "main"},
        {"owner": "a--b", "repository": "r", "branch": "main"},
        {"owner": "o" * 40, "repository": "r", "branch": "main"},
        {"owner": "o", "repository": "..", "branch": "main"},
        {"owner": "o", "repository": "a/b", "branch": "main"},
        {"owner": "o", "repository": "r", "branch": "../main"},
        {"owner": "o", "repository": "r", "branch": "main.lock"},
        {"owner": "o", "repository": "r", "branch": "feat//x"},
        {"owner": "o", "repository": "r", "branch": "a b"},
        {"owner": "o", "repository": "r", "branch": "main", "token": "x"},
    ],
)
def test_import_requests_are_validated(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        GitHubImportRequest.model_validate(fields)


def test_valid_import_request() -> None:
    request = GitHubImportRequest.model_validate(
        {"owner": "my-org", "repository": "code.walk_2", "branch": "feature/x-1"}
    )
    assert request.branch == "feature/x-1"


# --- archive reader -------------------------------------------------------------------------------


def archive(entries: list[tuple[str, bytes | None, str]]) -> bytes:
    """(name, content, kind) with kind file, symlink, hardlink, dir, fifo; names get GitHub's top folder."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content, kind in entries:
            info = tarfile.TarInfo(f"owner-repo-abc1234/{name}" if not name.startswith("/") else name)
            if kind == "file":
                info.size = len(content or b"")
                tar.addfile(info, io.BytesIO(content or b""))
                continue
            info.type = {
                "symlink": tarfile.SYMTYPE,
                "hardlink": tarfile.LNKTYPE,
                "dir": tarfile.DIRTYPE,
                "fifo": tarfile.FIFOTYPE,
            }[kind]
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    return buffer.getvalue()


def read(data: bytes, **limits: int) -> object:
    return read_archive(
        data,
        max_file_bytes=limits.get("max_file_bytes", 1000),
        max_files=limits.get("max_files", 100),
        max_total_bytes=limits.get("max_total_bytes", 1_000_000),
        deadline=time.monotonic() + 30,
    )


def test_archive_keeps_text_files_with_their_structure_and_skips_the_rest() -> None:
    data = archive(
        [
            ("src", None, "dir"),
            ("src/app.py", b"print('hi')\n", "file"),
            ("README.md", b"# Repo\n", "file"),
            ("src/link.py", None, "symlink"),
            ("src/hard.py", None, "hardlink"),
            ("dev/pipe", None, "fifo"),
            ("node_modules/x/index.js", b"x", "file"),
            (".env", b"KEY=value", "file"),
            ("deploy/id_rsa", b"-----BEGIN", "file"),
            ("logo.png", b"\x89PNG\x00\x00", "file"),
            ("latin1.txt", "caf\xe9".encode("latin-1"), "file"),
            ("big.py", b"x" * 1001, "file"),
        ]
    )
    contents = read(data)
    assert dict(contents.files) == {"src/app.py": "print('hi')\n", "README.md": "# Repo\n"}  # type: ignore[attr-defined]
    assert dict(contents.skipped) == {  # type: ignore[attr-defined]
        "src/link.py": "symlink",
        "src/hard.py": "symlink",
        "dev/pipe": "special_file",
        "node_modules/x/index.js": "ignored",
        ".env": "secret",
        "deploy/id_rsa": "secret",
        "logo.png": "binary",
        "latin1.txt": "binary",
        "big.py": "too_large",
    }


def test_traversal_names_are_passed_on_for_the_import_to_refuse() -> None:
    """The reader never writes anything; the stored path is validated by the file import."""
    contents = read(archive([("../../etc/evil.py", b"x", "file")]))
    assert [path for path, _ in contents.files] == ["../../etc/evil.py"]  # type: ignore[attr-defined]


def test_file_count_limit() -> None:
    contents = read(archive([(f"f{i}.py", b"x", "file") for i in range(5)]), max_files=3)
    assert len(contents.files) == 3  # type: ignore[attr-defined]
    assert [reason for _, reason in contents.skipped] == ["limit", "limit"]  # type: ignore[attr-defined]


def test_oversized_and_bomb_archives_are_refused() -> None:
    with pytest.raises(ArchiveTooLargeError):
        read(archive([(f"f{i}.py", b"x" * 900, "file") for i in range(5)]), max_total_bytes=2000)
    # Declared sizes far beyond the limit (files skipped as too large) still stop the read.
    with pytest.raises(ArchiveTooLargeError):
        read(
            archive([(f"f{i}.bin", b"\x00" * 5000, "file") for i in range(10)]),
            max_total_bytes=4000,
            max_file_bytes=100,
        )
    with pytest.raises(ArchiveTooLargeError, match="entries"):
        read(archive([(f"d{i}", None, "dir") for i in range(1100)]), max_files=1)


def test_invalid_archives_and_deadlines() -> None:
    with pytest.raises(ArchiveInvalidError):
        read(b"not a tarball")
    with pytest.raises(ArchiveTimeoutError):
        read_archive(
            archive([("a.py", b"x", "file")]),
            max_file_bytes=10,
            max_files=10,
            max_total_bytes=100,
            deadline=0,
        )
