"""Daily options-chain snapshot job.

For each configured ticker:
  1. fetch the underlying quote
  2. fetch expirations, keep those within max_expiration_days
  3. fetch each chain (with greeks), keep strikes within +/- strike_window_pct
     of spot, trim each contract to the fields the marts need
  4. upsert everything into Neon (re-runs for the same day are safe)

A per-ticker failure is logged and recorded but does not stop the other
tickers; the process exits non-zero at the end so CI still flags the run.

Usage:
    python -m ingestion.ingest_options [--force]

--force skips the market-calendar check (useful for weekend backtests of the
pipeline itself; data will just duplicate Friday's snapshot).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ingestion import db
from ingestion.config import Settings, load_settings
from ingestion.tradier import TradierClient

log = logging.getLogger("ingest_options")

# Contract fields kept in raw storage. Trimming here (not in dbt) is a
# deliberate free-tier tradeoff: full chains for 10 tickers would blow past
# Neon's 0.5 GB in weeks. See README "Storage budget".
CONTRACT_FIELDS = (
    "symbol",
    "strike",
    "expiration_date",
    "option_type",
    "bid",
    "ask",
    "last",
    "volume",
    "open_interest",
)
GREEK_FIELDS = ("delta", "gamma", "theta", "vega", "mid_iv")


def market_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def select_expirations(expirations: list[date], as_of: date, max_days: int) -> list[date]:
    return [e for e in expirations if 0 <= (e - as_of).days <= max_days]


def trim_contract(contract: dict) -> dict:
    trimmed = {k: contract.get(k) for k in CONTRACT_FIELDS}
    greeks = contract.get("greeks") or {}
    trimmed["greeks"] = {k: greeks.get(k) for k in GREEK_FIELDS}
    return trimmed


def filter_strikes(contracts: list[dict], spot: float, window_pct: float) -> list[dict]:
    lo, hi = spot * (1 - window_pct), spot * (1 + window_pct)
    return [c for c in contracts if c.get("strike") is not None and lo <= c["strike"] <= hi]


def ingest_ticker(
    client: TradierClient,
    conn,
    settings: Settings,
    snapshot_date: date,
    symbol: str,
    quote: dict,
) -> dict:
    spot = quote.get("last") or quote.get("prevclose")
    if not spot:
        raise ValueError(f"no usable price in quote for {symbol}")

    db.upsert_quote(conn, snapshot_date, symbol, quote)

    expirations = select_expirations(
        client.get_expirations(symbol), snapshot_date, settings.max_expiration_days
    )
    total_contracts = 0
    for expiration in expirations:
        chain = client.get_chain(symbol, expiration)
        contracts = [
            trim_contract(c)
            for c in filter_strikes(chain, spot, settings.strike_window_pct)
        ]
        db.upsert_chain(conn, snapshot_date, symbol, expiration, spot, contracts)
        total_contracts += len(contracts)

    conn.commit()
    return {"expirations": len(expirations), "contracts": total_contracts}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="run even if the market was closed")
    args = parser.parse_args(argv)

    settings = load_settings()
    client = TradierClient(settings.tradier_token, settings.tradier_base_url)
    snapshot_date = market_today()

    if not args.force and not client.is_trading_day(snapshot_date):
        log.info("market closed on %s; nothing to do", snapshot_date)
        return 0

    conn = db.connect(settings.database_url)
    db.ensure_schema(conn)
    run_id = db.start_run(conn, "ingest_options", snapshot_date)

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    quotes = {q.get("symbol"): q for q in client.get_quotes(settings.tickers)}
    for symbol in settings.tickers:
        try:
            quote = quotes.get(symbol)
            if quote is None:
                raise ValueError(f"no quote returned for {symbol}")
            results[symbol] = ingest_ticker(client, conn, settings, snapshot_date, symbol, quote)
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
