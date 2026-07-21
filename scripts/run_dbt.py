"""Run dbt with credentials derived from DATABASE_URL.

dbt-postgres wants host/user/password/dbname as separate fields, but this
pipeline keeps a single DATABASE_URL secret. This wrapper parses the URL into
the DBT_PG_* env vars that dbt/profiles.yml reads, then execs dbt with the
project/profiles dirs pinned. Works identically off a local .env and in CI.

Usage:
    python scripts/run_dbt.py build
    python scripts/run_dbt.py source freshness
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = PROJECT_ROOT / "dbt"


def pg_env_from_url(database_url: str) -> dict[str, str]:
    url = urlsplit(database_url)
    if not (url.hostname and url.username and url.password and url.path.lstrip("/")):
        raise SystemExit("DATABASE_URL must look like postgresql://user:pass@host/dbname")
    return {
        "DBT_PG_HOST": url.hostname,
        "DBT_PG_PORT": str(url.port or 5432),
        "DBT_PG_USER": unquote(url.username),
        "DBT_PG_PASSWORD": unquote(url.password),
        "DBT_PG_DBNAME": url.path.lstrip("/"),
    }


def main(argv: list[str]) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")

    env = {**os.environ, **pg_env_from_url(database_url)}
    cmd = [
        "dbt",
        *(argv or ["build"]),
        "--project-dir", str(DBT_DIR),
        "--profiles-dir", str(DBT_DIR),
    ]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
