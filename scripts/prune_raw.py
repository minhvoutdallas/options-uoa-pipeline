"""Delete raw options snapshots older than the configured retention window."""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RETENTION_DAYS = 90


def cutoff_date(today: date, retention_days: int) -> date:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    return today - timedelta(days=retention_days)


def prune(conn: psycopg.Connection, cutoff: date) -> dict[str, int]:
    counts = {}
    for table in ("option_chains", "underlying_quotes"):
        result = conn.execute(
            f"delete from raw.{table} where snapshot_date < %s",  # fixed allowlist
            (cutoff,),
        )
        counts[table] = result.rowcount
    conn.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")

    cutoff = cutoff_date(date.today(), args.days)
    with psycopg.connect(database_url) as conn:
        counts = prune(conn, cutoff)
    print(
        f"raw retention cutoff {cutoff}: "
        + ", ".join(f"{table}={count}" for table, count in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
