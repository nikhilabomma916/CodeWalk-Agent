"""Project scanning, structure extraction, and relationships on real on-disk test projects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from app.services.languages import Language, detect_language
from app.services.project_intelligence.javascript_structure import extract_javascript_structure
from app.services.project_intelligence.models import ProjectAnalysisResult, ProjectSummary, SymbolKind
from app.services.project_intelligence.project_analyzer import analyze_project
from app.services.project_intelligence.python_structure import extract_python_structure
from app.services.project_intelligence.scanner import ScanOptions, scan_directory

PROJECT_FILES: dict[str, str | bytes] = {
    "backend/app/__init__.py": "",
    "backend/app/main.py": (
        "from app.services.users import UserService\nfrom . import auth\nimport json\n\n"
        "service = UserService()\n"
    ),
    "backend/app/auth.py": "def login(user: str) -> bool:\n    return bool(user)\n",
    "backend/app/services/__init__.py": "",
    "backend/app/services/users.py": (
        "from ..database import connect\n\n\n"
        "class UserService:\n"
        "    @staticmethod\n"
        "    def create_user(name: str, *, admin: bool = False) -> dict:\n"
        "        return {'name': name}\n\n"
        "    async def load(self, user_id: int) -> None:\n"
        "        def helper():\n"
        "            return user_id\n"
        "        helper()\n"
    ),
    "backend/app/database.py": "def connect():\n    return None\n",
    "backend/app/broken.py": "def broken(:\n    pass\n",
    "frontend/tsconfig.json": '{\n  // aliases\n  "compilerOptions": {"paths": {"@/*": ["./src/*"]}},\n}\n',
    "frontend/src/api.ts": (
        "export interface User { id: number }\n"
        "export type Id = number;\n"
        "export async function fetchUser(id: Id): Promise<User> { return { id }; }\n"
        "export const baseUrl = '/api';\n"
    ),
    "frontend/src/component.tsx": (
        "import { fetchUser } from './api';\n"
        "import { baseUrl } from '@/api';\n"
        "import React from 'react';\n"
        "export default class Panel extends React.Component { render() { return <div>{baseUrl}</div>; } }\n"
        "export const load = async (id: number) => fetchUser(id);\n"
    ),
    "frontend/src/legacy.js": (
        "const fs = require('fs');\nimport('./api');\nfunction old() {}\nmodule.exports = { old };\n"
    ),
    "frontend/src/data.json": '{"a": 1}\n',
    "README.md": "# Project\n",
    "notes.xyz": "unknown extension\n",
    "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00binary",
    ".env": "SECRET_KEY=do-not-read\n",
    ".env.example": "SECRET_KEY=\n",
    "id_rsa": "-----BEGIN PRIVATE KEY-----\n",
    "scratch.tmp": "temp\n",
    "node_modules/react/index.js": "module.exports = {};\n",
    "backend/.venv/pyvenv.cfg": "home = x\n",
    "backend/.venv/lib/site.py": "x = 1\n",
    "backend/app/__pycache__/main.cpython-312.pyc": b"\x00\x01",
    "dist/bundle.js": "var a = 1;\n",
    "env/settings.py": "# 'env' here is real source, not a virtualenv\nDEBUG = True\n",
    "generated/output.txt": "ignored by .gitignore\n",
    ".gitignore": "generated/\n*.log\n",
    "debug.log": "ignored by .gitignore\n",
}


def write_project(root: Path, files: Mapping[str, str | bytes]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exact bytes: write_text would translate newlines on Windows.
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return write_project(tmp_path / "project", PROJECT_FILES)


@pytest.fixture
def result(project_root: Path) -> ProjectAnalysisResult:
    scan = scan_directory(project_root)
    return analyze_project(
        project=ProjectSummary(id=None, name="demo", root_path=None),
        files=scan.files,
        directories=scan.directories,
        skipped_count=len(scan.skipped),
    )


def file_info(result: ProjectAnalysisResult, path: str):  # type: ignore[no-untyped-def]
    return next(f for f in result.files if f.path == path)


# --- Scanner --------------------------------------------------------------------


def test_scanner_ignores_generated_secret_and_temporary_files(project_root: Path) -> None:
    scan = scan_directory(project_root)
    paths = {f.path for f in scan.files}
    skipped = {s.path: s.reason for s in scan.skipped}

    for ignored in ("node_modules", "backend/.venv", "backend/app/__pycache__", "dist"):
        assert skipped[ignored] in ("ignored directory", "virtual environment"), ignored
    assert skipped[".env"] == "secret file"
    assert skipped["id_rsa"] == "secret file"
    assert skipped["scratch.tmp"] == "temporary file"
    assert skipped["generated"] == "ignored by .gitignore"
    assert skipped["debug.log"] == "ignored by .gitignore"
    assert ".env.example" in paths  # templates are not secrets
    assert "env/settings.py" in paths  # "env" is kept when it is not a virtualenv
    assert not any("do-not-read" in (f.content or "") for f in scan.files)


def test_scanner_nested_folders_and_metadata(project_root: Path) -> None:
    scan = scan_directory(project_root)
    assert {"backend", "backend/app", "backend/app/services", "frontend/src"} <= set(scan.directories)
    main = next(f for f in scan.files if f.path == "backend/app/main.py")
    assert main.size == len(PROJECT_FILES["backend/app/main.py"])


def test_binary_and_large_files_are_not_read(project_root: Path) -> None:
    (project_root / "big.py").write_text("x = 1\n" * 1000, encoding="utf-8")
    scan = scan_directory(project_root, ScanOptions(max_file_bytes=1000))
    by_path = {f.path: f for f in scan.files}
    assert by_path["image.png"].content is None
    assert by_path["image.png"].skipped_reason == "binary or non-UTF-8"
    assert by_path["big.py"].content is None
    assert by_path["big.py"].skipped_reason == "too large"


def test_file_limit_truncates_scan(project_root: Path) -> None:
    scan = scan_directory(project_root, ScanOptions(max_files=3))
    assert len(scan.files) == 3
    assert scan.truncated


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    outside = write_project(tmp_path / "outside", {"secret.py": "TOKEN = 'x'\n"})
    root = write_project(tmp_path / "root", {"main.py": "x = 1\n"})
    try:
        os.symlink(outside, root / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires extra privileges on this platform")
    scan = scan_directory(root)
    assert [f.path for f in scan.files] == ["main.py"]
    assert {s.path: s.reason for s in scan.skipped}["linked"] == "symbolic link"


def test_empty_project(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    scan = scan_directory(tmp_path / "empty")
    result = analyze_project(project=ProjectSummary(id=None, name="e", root_path=None), files=scan.files)
    assert result.files == []
    assert result.statistics.total_files == 0
    assert result.relationships == []


def test_scan_root_must_be_a_directory(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        scan_directory(tmp_path / "missing")


# --- Language detection -----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("a.py", Language.PYTHON),
        ("a.js", Language.JAVASCRIPT),
        ("a.jsx", Language.JAVASCRIPT_REACT),
        ("a.ts", Language.TYPESCRIPT),
        ("a.tsx", Language.TYPESCRIPT_REACT),
        ("a.json", Language.JSON),
        ("a.html", Language.HTML),
        ("a.css", Language.CSS),
        ("a.sql", Language.SQL),
        ("a.md", Language.MARKDOWN),
        ("A.java", Language.JAVA),
        ("a.c", Language.C),
        ("a.cpp", Language.CPP),
        ("Dockerfile", Language.DOCKERFILE),
        ("a.xyz", Language.UNKNOWN),
        ("LICENSE", Language.UNKNOWN),
        ("src/UPPER.PY", Language.PYTHON),
    ],
)
def test_language_detection(path: str, language: Language) -> None:
    assert detect_language(path) is language


# --- Python structure ----------------------------------------------------------


def test_python_classes_methods_functions_decorators_async() -> None:
    structure = extract_python_structure(
        "backend/app/services/users.py", str(PROJECT_FILES["backend/app/services/users.py"])
    )
    symbols = {s.qualified_name: s for s in structure.symbols}

    cls = symbols["UserService"]
    assert cls.kind is SymbolKind.CLASS
    assert cls.line == 4

    create = symbols["UserService.create_user"]
    assert create.kind is SymbolKind.METHOD
    assert create.parent == cls.id
    assert create.decorators == ["staticmethod"]
    assert create.parameters == ["name", "admin"]
    assert create.return_annotation == "dict"
    assert create.signature == "def create_user(name: str, *, admin: bool=False) -> dict"

    load = symbols["UserService.load"]
    assert load.is_async
    assert load.signature is not None
    assert load.signature.startswith("async def load(self, user_id: int)")

    helper = symbols["UserService.load.helper"]
    assert helper.kind is SymbolKind.FUNCTION  # nested function
    assert helper.parent == load.id

    [imported] = structure.imports
    assert (imported.module, imported.level, imported.names) == ("database", 2, ["connect"])


def test_python_parse_error_is_reported_not_raised() -> None:
    structure = extract_python_structure("broken.py", "def broken(:\n    pass\n")
    assert structure.symbols == []
    assert structure.parse_error is not None
    assert "line 1" in structure.parse_error


# --- JavaScript / TypeScript structure ------------------------------------------


def test_typescript_structure() -> None:
    structure = extract_javascript_structure(
        "api.ts", str(PROJECT_FILES["frontend/src/api.ts"]), Language.TYPESCRIPT
    )
    kinds = {s.name: s.kind for s in structure.symbols}
    assert kinds == {
        "User": SymbolKind.INTERFACE,
        "Id": SymbolKind.TYPE_ALIAS,
        "fetchUser": SymbolKind.FUNCTION,
        "baseUrl": SymbolKind.VARIABLE,
    }
    fetch = next(s for s in structure.symbols if s.name == "fetchUser")
    assert fetch.is_async
    assert fetch.parameters == ["id"]
    assert fetch.return_annotation == "Promise<User>"
    assert set(structure.exports) == {"User", "Id", "fetchUser", "baseUrl"}


def test_tsx_class_methods_imports_and_default_export() -> None:
    structure = extract_javascript_structure(
        "component.tsx", str(PROJECT_FILES["frontend/src/component.tsx"]), Language.TYPESCRIPT_REACT
    )
    names = {s.qualified_name: s for s in structure.symbols}
    assert names["Panel"].kind is SymbolKind.CLASS
    assert names["Panel.render"].kind is SymbolKind.METHOD
    assert names["load"].kind is SymbolKind.FUNCTION
    assert [(i.module, i.names) for i in structure.imports] == [
        ("./api", ["fetchUser"]),
        ("@/api", ["baseUrl"]),
        ("react", ["React"]),
    ]
    assert "default" in structure.exports


def test_commonjs_require_and_dynamic_import() -> None:
    structure = extract_javascript_structure(
        "legacy.js", str(PROJECT_FILES["frontend/src/legacy.js"]), Language.JAVASCRIPT
    )
    assert [(i.module, i.kind.value) for i in structure.imports] == [
        ("fs", "require"),
        ("./api", "dynamic_import"),
    ]
    assert "old" in {s.name for s in structure.symbols}


def test_javascript_syntax_errors_still_return_partial_structure() -> None:
    structure = extract_javascript_structure(
        "x.js", "function ok() {}\nfunction broken( {\n", Language.JAVASCRIPT
    )
    assert structure.parse_error is not None
    assert "ok" in {s.name for s in structure.symbols}


# --- Whole project ----------------------------------------------------------------


def test_malformed_file_does_not_stop_the_scan(result: ProjectAnalysisResult) -> None:
    assert [(e.path, e.stage) for e in result.errors] == [("backend/app/broken.py", "parse")]
    # Every other file was still analyzed.
    assert file_info(result, "backend/app/services/users.py").symbols
    assert file_info(result, "frontend/src/api.ts").symbols


def test_import_relationships(result: ProjectAnalysisResult) -> None:
    imports = {(r.source, r.target) for r in result.relationships if r.kind.value == "imports"}
    assert (
        "backend/app/main.py",
        "backend/app/services/users.py",
    ) in imports  # absolute, source root detected
    assert ("backend/app/main.py", "backend/app/auth.py") in imports  # from . import auth
    assert ("backend/app/services/users.py", "backend/app/database.py") in imports  # from ..database
    assert ("frontend/src/component.tsx", "frontend/src/api.ts") in imports  # relative and via @/ alias
    assert ("backend/app/main.py", "json") in imports  # external module, not resolved to a file
    external = next(r for r in result.relationships if r.target == "react")
    assert external.target_kind.value == "module"


def test_defines_and_contains_relationships(result: ProjectAnalysisResult) -> None:
    relationships = {(r.source, r.target, r.kind.value) for r in result.relationships}
    users = "backend/app/services/users.py"
    assert (users, f"{users}::UserService", "defines") in relationships
    assert (f"{users}::UserService", f"{users}::UserService.create_user", "contains") in relationships


def test_statistics(result: ProjectAnalysisResult) -> None:
    stats = result.statistics
    assert stats.total_files == len(result.files)
    languages = {s.language: s.files for s in stats.languages}
    assert languages[Language.PYTHON] == 8
    # notes.xyz, image.png (binary, still listed), .gitignore, .env.example
    assert languages[Language.UNKNOWN] == 4
    assert stats.symbol_counts["class"] >= 2
    assert stats.internal_imports >= 5
    assert stats.external_imports >= 3
    assert stats.analysis_errors == 1
    assert stats.skipped_files > 0
    assert stats.largest_files[0].size >= stats.largest_files[-1].size


def test_unknown_extension_is_listed_without_structure(result: ProjectAnalysisResult) -> None:
    info = file_info(result, "notes.xyz")
    assert info.language is Language.UNKNOWN
    assert info.structure_supported is False
    assert info.symbols == []


def test_credential_folders_and_names_are_secret(tmp_path: Path) -> None:
    """Regression (Module 14): credentials identified by folder or by well-known name are never scanned."""
    from app.services.project_intelligence.scanner import is_secret_path, scan_directory

    for path in (
        ".aws/credentials",
        "a/.kube/config",
        ".ssh/config",
        "credentials.json",
        "secrets.yaml",
        "infra/prod.tfstate",
        ".env.local",
        "keys/id_ed25519",
    ):
        assert is_secret_path(path), path
    for path in ("src/credentials.py", "docs/secrets.md", ".env.example", "aws/handler.py", "kube/README.md"):
        assert not is_secret_path(path), path

    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "credentials").write_text("aws_secret_access_key = FAKE\n")
    (tmp_path / "secrets.yaml").write_text("token: FAKE\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    result = scan_directory(tmp_path)
    assert [f.path for f in result.files] == ["app.py"]
    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons[".aws"] == "secret directory"
    assert reasons["secrets.yaml"] == "secret file"
