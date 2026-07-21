"""Unit tests for the fundamentals job's pure logic (no network, no db)."""

from datetime import date, datetime

from ingestion.ingest_fundamentals import (
    FUNDAMENTAL_FIELDS,
    serialize_earnings_dates,
    trim_info,
)


def test_trim_info_keeps_only_configured_fields():
    info = {
        "longName": "Apple Inc.",
        "marketCap": 3_000_000_000_000,
        "irrelevantKey": "dropped",
        "regularMarketPrice": 210.0,
    }
    trimmed = trim_info(info)
    assert set(trimmed) == set(FUNDAMENTAL_FIELDS)
    assert trimmed["longName"] == "Apple Inc."
    assert "irrelevantKey" not in trimmed


def test_trim_info_missing_fields_become_none():
    trimmed = trim_info({})
    assert all(v is None for v in trimmed.values())


def test_serialize_earnings_dates_handles_dates_and_datetimes():
    dates = [date(2026, 7, 30), datetime(2026, 10, 29, 16, 30)]
    assert serialize_earnings_dates(dates) == ["2026-07-30", "2026-10-29"]


def test_serialize_earnings_dates_drops_non_dates():
    assert serialize_earnings_dates(["not a date", None, 42]) == []
