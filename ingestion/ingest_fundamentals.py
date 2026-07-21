"""Weekly company-fundamentals snapshot job (yfinance).

For each configured ticker, fetch Yahoo Finance's summary info, trim it to the
fields the marts care about, tack on upcoming earnings dates, and upsert one
JSONB row per (snapshot_date, symbol) into Neon.

yfinance is an unofficial API and individual tickers fail or rate-limit from
time to time, so failures are isolated per ticker exactly like the options job.
ETFs (SPY, QQQ) simply land with nulls for the equity-only fields.

Usage:
    python -m ingestion.ingest_fundamentals
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from ingestion import db
from ingestion.config import load_settings

log = logging.getLogger("ingest_fundamentals")

# Fields kept from yfinance's ~150-key info blob. Same free-tier tradeoff as
# the options job: trim in Python so raw storage stays small.
FUNDAMENTAL_FIELDS = (
    "longName",
    "quoteType",
    "sector",
    "industry",
    "marketCap",
    "trailingPE",
    "forwardPE",
    "trailingEps",
    "priceToSalesTrailing12Months",
    "profitMargins",
    "revenueGrowth",
    "beta",
    "sharesOutstanding",
    "shortPercentOfFloat",
    "dividendYield",
)


def market_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def trim_info(info: dict) -> dict:
    return {k: info.get(k) for k in FUNDAMENTAL_FIELDS}


def serialize_earnings_dates(dates: list) -> list[str]:
    """Normalize yfinance calendar entries (date/datetime) to ISO date strings."""
    out = []
    for d in dates:
        if isinstance(d, datetime):
            d = d.date()
        if isinstance(d, date):
            out.append(d.isoformat())
    return out


def fetch_fundamentals(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    payload = trim_info(ticker.info or {})
    try:
        calendar = ticker.calendar or {}
        payload["earnings_dates"] = serialize_earnings_dates(calendar.get("Earnings Date") or [])
    except Exception:  # noqa: BLE001 - calendar is flakier than info; not worth failing the ticker
        log.warning("%s: could not fetch earnings calendar", symbol)
        payload["earnings_dates"] = []
    return payload


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = load_settings(require_tradier=False)
    snapshot_date = market_today()

    conn = db.connect(settings.database_url)
    db.ensure_schema(conn)
    run_id = db.start_run(conn, "ingest_fundamentals", snapshot_date)

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for symbol in settings.tickers:
        try:
            payload = fetch_fundamentals(symbol)
            db.upsert_fundamentals(conn, snapshot_date, symbol, payload)
            conn.commit()
            results[symbol] = {"fields": sum(v is not None for v in payload.values())}
            log.info("%s: %s", symbol, results[symbol])
        except Exception as exc:  # noqa: BLE001 - isolate per-ticker failures
            conn.rollback()
            errors[symbol] = str(exc)
            log.exception("failed to ingest %s", symbol)

    status = "success" if not errors else ("partial" if results else "failed")
    db.finish_run(conn, run_id, status, {"results": results, "errors": errors})
    conn.close()

    log.info("run finished: %s (%d ok, %d failed)", status, len(results), len(errors))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
