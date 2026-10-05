"""Production preflight: ``python -m app.preflight [--no-db] [--json]`` (Module 22).

Run it with the deployment's environment before switching traffic (in CI, from a trusted machine, or
inside the image) to check that the configuration loads under production rules, that optional
integrations are either fully configured or off, and that the database is reachable, has pgvector,
and is migrated to the code's Alembic head. It prints only names and states (PASS / WARN / FAIL),
never configuration values, and exits with 1 when anything fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Environment, Settings

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def configuration_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str, *, warn: bool = False) -> None:
        checks.append(Check(name, "PASS" if ok else ("WARN" if warn else "FAIL"), detail))

    production = settings.env is Environment.PRODUCTION
    add("environment", production, f"CODEWALK_ENV={settings.env.value}", warn=True)
    add(
        "database_url",
        settings.database_url is not None,
        "CODEWALK_DATABASE_URL is "
        + ("set" if settings.database_url else "not set (persistence is required)"),
    )
    add(
        "session_cookie",
        settings.cookie_secure,
        "Secure cookies " + ("on" if settings.cookie_secure else "off"),
        warn=not production,
    )
    origins = settings.allowed_origins
    add(
        "allowed_origins",
        all(origin.startswith("https://") for origin in origins),
        f"{len(origins)} allowed origin(s)" + (" (same origin only)" if not origins else ""),
        warn=not production,
    )

    if settings.ai_enabled:
        from app.services.ai.providers import UnknownProviderError, create_provider

        try:
            status = create_provider(settings).status()
            add(
                "ai_provider",
                status.configured,
                f"{status.provider}: "
                + ("configured" if status.configured else (status.detail or "not configured")),
            )
        except UnknownProviderError:
            add("ai_provider", False, "CODEWALK_AI_PROVIDER names an unknown provider")
        if settings.ai_provider_name == "ollama" and production:
            add(
                "ai_ollama",
                False,
                "Ollama selected in production: reachable only if self-hosted behind https",
                warn=True,
            )
    else:
        add("ai_provider", True, "AI assistance is off")

    if settings.rag_enabled:
        from app.services.retrieval.providers import create_embedding_provider

        state = create_embedding_provider(settings).status()
        add(
            "rag_provider",
            state.configured,
            "embeddings " + ("configured" if state.configured else "not configured"),
        )
    else:
        add("rag_provider", True, "semantic retrieval is off")

    github_parts = {
        "CODEWALK_GITHUB_CLIENT_ID": bool(settings.github_client_id),
        "CODEWALK_GITHUB_CLIENT_SECRET": bool(settings.github_client_secret),
        "CODEWALK_GITHUB_CALLBACK_URL": bool(settings.github_callback_url),
        "CODEWALK_TOKEN_ENCRYPTION_KEY": bool(settings.token_encryption_key),
    }
    if all(github_parts.values()):
        add(
            "github",
            True,
            "configured" + (" (private repositories)" if "repo" in settings.github_scopes else ""),
        )
    elif any(github_parts.values()):
        missing = ", ".join(name for name, present in github_parts.items() if not present)
        add("github", False, f"partly configured; missing: {missing}")
    else:
        add("github", True, "off")
    return checks


def database_checks(settings: Settings) -> list[Check]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import Database

    database = Database.from_settings(settings)
    if database is None:
        return [Check("database", "FAIL", "CODEWALK_DATABASE_URL is not set")]
    checks: list[Check] = []
    try:
        with database.engine.connect() as connection:
            version: str = str(connection.execute(text("SHOW server_version")).scalar_one())
            checks.append(Check("database", "PASS", f"connected (PostgreSQL {str(version).split()[0]})"))
            vector = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            available = connection.execute(
                text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar()
            if vector:
                checks.append(Check("pgvector", "PASS", f"extension vector {vector} installed"))
            elif available:
                checks.append(
                    Check(
                        "pgvector",
                        "WARN",
                        f"available ({available}) but not installed yet: the migrations install it",
                    )
                )
            else:
                checks.append(
                    Check("pgvector", "FAIL", "the vector extension is not available on this server")
                )
            has_table = connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar()
            current = (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if has_table
                else None
            )
    except SQLAlchemyError as exc:
        return [Check("database", "FAIL", f"cannot connect or query ({type(exc).__name__})")]
    finally:
        database.dispose()
    head = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()
    if current == head:
        checks.append(Check("schema", "PASS", f"migrated to head {head}"))
    else:
        checks.append(
            Check(
                "schema", "FAIL", f"at {current or 'no revision'}; the code needs {head} (run the migration)"
            )
        )
    return checks


def run(*, with_database: bool, with_configuration: bool = True) -> list[Check]:
    try:
        settings = Settings()
    except ValidationError as exc:
        # Messages name the setting and the rule; input values are hidden (hide_input_in_errors).
        return [Check("configuration", "FAIL", error["msg"]) for error in exc.errors()]
    checks = [Check("configuration", "PASS", "settings load under the configured rules")]
    if with_configuration:
        checks.extend(configuration_checks(settings))
    if with_database:
        checks.extend(database_checks(settings))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.preflight", description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-db", action="store_true", help="skip the database checks")
    parser.add_argument("--db-only", action="store_true", help="only the database checks (for migrations)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    checks = run(with_database=not args.no_db, with_configuration=not args.db_only)
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        for check in checks:
            print(f"{check.status:4}  {check.name:16} {check.detail}")
    failed = any(check.status == "FAIL" for check in checks)
    print(f"\npreflight: {'FAILED' if failed else 'ok'}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
