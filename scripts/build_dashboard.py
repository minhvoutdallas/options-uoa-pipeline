"""Snapshot the marts into a self-contained dashboard HTML file.

The serving layer is a *static* site: this script queries the dbt marts in Neon,
shapes them into one JSON payload, and injects that payload into
``dashboard/template.html`` to produce ``dashboard/dist/index.html`` — a single,
dependency-free file that GitHub Pages serves for $0. It regenerates on every
daily cron right after ``dbt build``, so the published page is never more than a
snapshot behind the warehouse.

Everything the page needs is embedded at build time; the browser makes no network
calls, so there is no CORS/datasource/secret surface on the public page.

Usage:
    python scripts/build_dashboard.py                 # off .env or CI env
    python scripts/build_dashboard.py --out some.html # override output path
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "dashboard" / "template.html"
DEFAULT_OUT = PROJECT_ROOT / "dashboard" / "dist" / "index.html"

# Mirror of config/pipeline.yml uoa block — displayed on the page so a reader
# knows the rule the flags were evaluated against. Loaded from the yaml at build
# time (below) rather than hardcoded, so it can never drift.


def _num(value):
    """Postgres numerics arrive as Decimal; JSON wants float/None."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, (_num(v) for v in row))) for row in cur.fetchall()]


def _one(cur, sql, params=None):
    rows = _rows(cur, sql, params)
    return rows[0] if rows else {}


def load_thresholds() -> dict:
    import yaml

    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "pipeline.yml").read_text("utf-8"))
    uoa = cfg["uoa"]
    return {
        "ntm_pct": float(uoa["ntm_pct"]),
        "baseline_days": int(uoa["baseline_days"]),
        "volume_multiple": float(uoa["volume_multiple"]),
        "tickers_tracked": len(cfg["tickers"]),
    }


def build_payload(conn: psycopg.Connection) -> dict:
    thresholds = load_thresholds()
    baseline_days = thresholds["baseline_days"]

    with conn.cursor() as cur:
        latest = _one(cur, "select max(snapshot_date) as d from marts.fct_uoa_flags")
        latest_date = latest.get("d")
        if latest_date is None:
            raise SystemExit("marts.fct_uoa_flags is empty — run the pipeline first")

        history = _one(
            cur,
            """
            select count(distinct snapshot_date) as days,
                   min(snapshot_date) as first_day,
                   max(baseline_days_available) as baseline_available
            from marts.fct_uoa_flags
            """,
        )

        # One row per ticker for the latest day, calls and puts pivoted side by
        # side and joined to the fundamentals/earnings overlay.
        tickers = _rows(
            cur,
            """
            with f as (
                select * from marts.fct_uoa_flags where snapshot_date = %(d)s
            ),
            pivoted as (
                select
                    underlying as symbol,
                    max(spot_price) as spot,
                    max(spot_price) filter (where option_type = 'call') as spot_c,
                    sum(ntm_volume) filter (where option_type = 'call') as call_volume,
                    sum(ntm_volume) filter (where option_type = 'put')  as put_volume,
                    sum(ntm_open_interest) filter (where option_type = 'call') as call_oi,
                    sum(ntm_open_interest) filter (where option_type = 'put')  as put_oi,
                    max(ntm_vw_implied_vol) filter (where option_type = 'call') as call_iv,
                    max(ntm_vw_implied_vol) filter (where option_type = 'put')  as put_iv,
                    max(volume_ratio) filter (where option_type = 'call') as call_ratio,
                    max(volume_ratio) filter (where option_type = 'put')  as put_ratio,
                    bool_or(is_uoa) as is_uoa,
                    bool_or(is_uoa) filter (where option_type = 'call') as call_uoa,
                    bool_or(is_uoa) filter (where option_type = 'put')  as put_uoa
                from f
                group by underlying
            )
            select
                p.symbol,
                p.spot,
                p.call_volume, p.put_volume, p.call_oi, p.put_oi,
                p.call_iv, p.put_iv, p.call_ratio, p.put_ratio,
                p.is_uoa, p.call_uoa, p.put_uoa,
                c.company_name, c.sector, c.industry,
                c.market_cap, c.trailing_pe, c.forward_pe, c.beta,
                c.next_earnings_date,
                case when c.next_earnings_date is not null
                     then (c.next_earnings_date - %(d)s) end as days_to_earnings
            from pivoted p
            left join marts.dim_company c on c.symbol = p.symbol
            order by (coalesce(p.call_volume,0) + coalesce(p.put_volume,0)) desc
            """,
            {"d": latest_date},
        )

        # UOA flag feed — most recent flags across all history, richest first.
        flags = _rows(
            cur,
            """
            select
                f.snapshot_date, f.underlying as symbol, f.option_type,
                f.spot_price as spot, f.ntm_volume, f.ntm_open_interest,
                f.baseline_ntm_volume, f.volume_ratio,
                c.company_name, c.next_earnings_date,
                case when c.next_earnings_date is not null
                     then (c.next_earnings_date - f.snapshot_date) end as days_to_earnings
            from marts.fct_uoa_flags f
            left join marts.dim_company c on c.symbol = f.underlying
            where f.is_uoa
            order by f.snapshot_date desc, f.volume_ratio desc nulls last
            limit 50
            """,
        )

        # Per-ticker daily series for the volume-vs-baseline charts. Calls and
        # puts pivoted; baseline is the same trailing average the rule uses.
        series = _rows(
            cur,
            """
            select
                snapshot_date,
                underlying as symbol,
                sum(ntm_volume) filter (where option_type = 'call') as call_volume,
                sum(ntm_volume) filter (where option_type = 'put')  as put_volume,
                avg(baseline_ntm_volume) as baseline
            from marts.fct_uoa_flags
            group by snapshot_date, underlying
            order by underlying, snapshot_date
            """,
        )
        timeseries: dict[str, list] = {}
        for r in series:
            timeseries.setdefault(r["symbol"], []).append(
                {
                    "date": r["snapshot_date"].isoformat(),
                    "call_volume": r["call_volume"],
                    "put_volume": r["put_volume"],
                    "baseline": r["baseline"],
                }
            )

        # Market-wide daily totals for the headline trend.
        market = _rows(
            cur,
            """
            select
                snapshot_date,
                sum(ntm_volume) filter (where option_type = 'call') as call_volume,
                sum(ntm_volume) filter (where option_type = 'put')  as put_volume,
                count(*) filter (where is_uoa) as flags
            from marts.fct_uoa_flags
            group by snapshot_date
            order by snapshot_date
            """,
        )

        # Pipeline health — the most recent runs of each job.
        runs = _rows(
            cur,
            """
            select run_id, job, snapshot_date, started_at, finished_at, status
            from raw.ingest_runs
            order by started_at desc
            limit 8
            """,
        )

    # ---- headline KPIs (latest day) --------------------------------------
    total_call = sum((t["call_volume"] or 0) for t in tickers)
    total_put = sum((t["put_volume"] or 0) for t in tickers)
    active_flags = sum(1 for t in tickers if t["is_uoa"])
    upcoming_earnings = sum(
        1
        for t in tickers
        if t["days_to_earnings"] is not None and 0 <= t["days_to_earnings"] <= 7
    )
    kpis = {
        "tickers_tracked": thresholds["tickers_tracked"],
        "latest_date": latest_date.isoformat(),
        "total_ntm_volume": total_call + total_put,
        "market_pcr": (total_put / total_call) if total_call else None,
        "active_flags": active_flags,
        "history_days": history["days"],
        "baseline_available": history["baseline_available"] or 0,
        "baseline_required": baseline_days,
        "upcoming_earnings": upcoming_earnings,
    }

    def norm(rows):
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, (date, datetime)):
                    r[k] = v.isoformat()
        return rows

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_date": latest_date.isoformat(),
        "thresholds": thresholds,
        "kpis": kpis,
        "tickers": norm(tickers),
        "flags": norm(flags),
        "timeseries": timeseries,
        "market": norm(market),
        "runs": norm(runs),
    }


def render(payload: dict, template: str) -> str:
    """Inject the data payload into the (body-only) template."""
    blob = json.dumps(payload, separators=(",", ":"))
    if "__DASHBOARD_DATA__" not in template:
        raise SystemExit("template is missing the __DASHBOARD_DATA__ placeholder")
    return template.replace("__DASHBOARD_DATA__", blob)


PAGE_SKELETON = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Unusual options activity monitor — daily NTM flow vs a trailing baseline across 10 liquid tickers.">
<title>Options UOA Monitor</title>
</head>
<body>
{body}
</body>
</html>
"""


def wrap_page(body: str) -> str:
    """Wrap body content in a standalone HTML document for GitHub Pages.

    The template is body-only so the identical content can be published as a
    Claude Artifact (which supplies its own skeleton); Pages needs the full
    document, added here.
    """
    return PAGE_SKELETON.format(body=body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--body-only",
        action="store_true",
        help="emit just the body content (for publishing as a Claude Artifact) "
        "instead of a full standalone HTML document",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")

    with psycopg.connect(database_url) as conn:
        payload = build_payload(conn)

    body = render(payload, TEMPLATE_PATH.read_text("utf-8"))
    html = body if args.body_only else wrap_page(body)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    kpis = payload["kpis"]
    print(
        f"dashboard -> {args.out}  "
        f"({kpis['tickers_tracked']} tickers, {kpis['history_days']}d history, "
        f"{kpis['active_flags']} active flags, "
        f"baseline {kpis['baseline_available']}/{kpis['baseline_required']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
