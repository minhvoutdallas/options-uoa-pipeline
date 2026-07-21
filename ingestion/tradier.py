"""Thin Tradier REST client.

Handles the three things every Tradier consumer needs:
- auth header + JSON accept header
- client-side throttling (sandbox allows 60 market-data requests/min)
- retry with exponential backoff on 429s and transient 5xx/network errors

Tradier quirk worth knowing: list-shaped responses collapse to a bare object
when there is exactly one element, and to null when empty. ``as_list``
normalizes all three shapes and is unit-tested for it.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


class TradierError(Exception):
    """Non-retryable API failure (4xx other than 429, malformed response)."""


class TradierRetryableError(Exception):
    """Transient failure worth retrying (429, 5xx, network error)."""


def as_list(value) -> list:
    """Normalize Tradier's list/single-object/null polymorphism to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class TradierClient:
    def __init__(self, token: str, base_url: str, min_interval_s: float = 1.1):
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = min_interval_s
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    @retry(
        retry=retry_if_exception_type(TradierRetryableError),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, path: str, params: dict) -> dict:
        # Throttle: space requests at least min_interval_s apart.
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_request_at = time.monotonic()

        try:
            resp = self._session.get(f"{self.base_url}{path}", params=params, timeout=30)
        except requests.RequestException as exc:
            raise TradierRetryableError(f"network error on {path}: {exc}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise TradierRetryableError(f"HTTP {resp.status_code} on {path}")
        if resp.status_code != 200:
            raise TradierError(f"HTTP {resp.status_code} on {path}: {resp.text[:300]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise TradierError(f"non-JSON response on {path}") from exc

    def get_quotes(self, symbols: list[str]) -> list[dict]:
        data = self._get("/markets/quotes", {"symbols": ",".join(symbols)})
        return as_list((data.get("quotes") or {}).get("quote"))

    def get_expirations(self, symbol: str) -> list[date]:
        data = self._get(
            "/markets/options/expirations",
            {"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
        )
        dates = as_list((data.get("expirations") or {}).get("date"))
        return [date.fromisoformat(d) for d in dates]

    def get_chain(self, symbol: str, expiration: date) -> list[dict]:
        data = self._get(
            "/markets/options/chains",
            {"symbol": symbol, "expiration": expiration.isoformat(), "greeks": "true"},
        )
        return as_list((data.get("options") or {}).get("option"))

    def is_trading_day(self, d: date) -> bool:
        data = self._get("/markets/calendar", {"month": d.month, "year": d.year})
        days = as_list(((data.get("calendar") or {}).get("days") or {}).get("day"))
        for day in days:
            if day.get("date") == d.isoformat():
                return day.get("status") == "open"
        log.warning("date %s not found in Tradier calendar; assuming closed", d)
        return False
