"""Send newly detected UOA flags to Discord exactly once.

By default only the latest modeled snapshot is considered. Successful
deliveries are recorded in ``raw.uoa_alert_deliveries`` so retries are safe.
If DISCORD_WEBHOOK_URL is absent the command exits successfully, allowing the
integration to remain optional in forks and local development.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def format_alert(flag: dict) -> dict:
    side = str(flag["option_type"]).upper()
    ratio = flag.get("volume_ratio")
    ratio_text = f"{float(ratio):.1f}x" if ratio is not None else "n/a"
    description = (
        f"**{flag['underlying']} {side}** · {flag['snapshot_date']}\n"
        f"NTM volume **{int(flag['ntm_volume']):,}** · "
        f"open interest **{int(flag['ntm_open_interest']):,}** · "
        f"baseline **{float(flag['baseline_ntm_volume']):,.0f}** · "
        f"ratio **{ratio_text}**"
    )
    return {
        "username": "Options UOA Monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "Unusual options activity detected",
                "description": description,
                "color": 0xF59E0B if side == "CALL" else 0x8B5CF6,
                "footer": {"text": "Daily near-the-money chain snapshot"},
            }
        ],
    }


def pending_flags(conn: psycopg.Connection, snapshot_date: date | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                f.snapshot_date, f.underlying, f.option_type, f.ntm_volume,
                f.ntm_open_interest, f.baseline_ntm_volume, f.volume_ratio
            from marts.fct_uoa_flags f
            left join raw.uoa_alert_deliveries d
              on d.snapshot_date = f.snapshot_date
             and d.underlying = f.underlying
             and d.option_type = f.option_type
            where f.is_uoa
              and d.snapshot_date is null
              and f.snapshot_date = coalesce(
                    %(snapshot_date)s,
                    (select max(snapshot_date) from marts.fct_uoa_flags)
                  )
            order by f.volume_ratio desc nulls last, f.underlying, f.option_type
            """,
            {"snapshot_date": snapshot_date},
        )
        columns = [d.name for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def record_delivery(conn: psycopg.Connection, flag: dict, payload: dict) -> None:
    conn.execute(
        """
        insert into raw.uoa_alert_deliveries
            (snapshot_date, underlying, option_type, payload)
        values (%s, %s, %s, %s)
        on conflict (snapshot_date, underlying, option_type) do nothing
        """,
        (
            flag["snapshot_date"],
            flag["underlying"],
            flag["option_type"],
            json.dumps(payload),
        ),
    )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", type=date.fromisoformat)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set; skipping UOA notifications")
        return 0

    with psycopg.connect(database_url) as conn:
        flags = pending_flags(conn, args.snapshot_date)
        for flag in flags:
            payload = format_alert(flag)
            response = requests.post(webhook_url, json=payload, timeout=20)
            response.raise_for_status()
            record_delivery(conn, flag, payload)

    print(f"Discord alerts delivered: {len(flags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
