"""Neon Postgres access: schema bootstrap, idempotent upserts, run logging."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def upsert_quote(conn: psycopg.Connection, snapshot_date: date, symbol: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT INTO raw.underlying_quotes (snapshot_date, symbol, payload)
        VALUES (%s, %s, %s)
        ON CONFLICT (snapshot_date, symbol)
        DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
        """,
        (snapshot_date, symbol, json.dumps(payload)),
    )


def upsert_chain(
    conn: psycopg.Connection,
    snapshot_date: date,
    underlying: str,
    expiration: date,
    spot_price: float,
    contracts: list[dict],
) -> None:
    conn.execute(
        """
        INSERT INTO raw.option_chains
            (snapshot_date, underlying, expiration, spot_price, payload, contract_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (snapshot_date, underlying, expiration)
        DO UPDATE SET spot_price = EXCLUDED.spot_price,
                      payload = EXCLUDED.payload,
                      contract_count = EXCLUDED.contract_count,
                      ingested_at = now()
        """,
        (snapshot_date, underlying, expiration, spot_price, json.dumps(contracts), len(contracts)),
    )


def upsert_fundamentals(
    conn: psycopg.Connection, snapshot_date: date, symbol: str, payload: dict
) -> None:
    conn.execute(
        """
        INSERT INTO raw.fundamentals (snapshot_date, symbol, payload)
        VALUES (%s, %s, %s)
        ON CONFLICT (snapshot_date, symbol)
        DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
        """,
        (snapshot_date, symbol, json.dumps(payload)),
    )


def start_run(conn: psycopg.Connection, job: str, snapshot_date: date) -> int:
    row = conn.execute(
        """
        INSERT INTO raw.ingest_runs (job, snapshot_date, started_at)
        VALUES (%s, %s, %s)
        RETURNING run_id
        """,
        (job, snapshot_date, datetime.now(timezone.utc)),
    ).fetchone()
    conn.commit()
    return row[0]


def finish_run(conn: psycopg.Connection, run_id: int, status: str, detail: dict) -> None:
    conn.execute(
        """
        UPDATE raw.ingest_runs
        SET finished_at = %s, status = %s, detail = %s
        WHERE run_id = %s
        """,
        (datetime.now(timezone.utc), status, json.dumps(detail), run_id),
    )
    conn.commit()
