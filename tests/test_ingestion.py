from datetime import date

from ingestion.ingest_options import filter_strikes, select_expirations, trim_contract
from ingestion.tradier import as_list


class TestAsList:
    """Tradier collapses one-element lists to a bare object and empty to null."""

    def test_none_becomes_empty(self):
        assert as_list(None) == []

    def test_single_object_is_wrapped(self):
        assert as_list({"symbol": "AAPL"}) == [{"symbol": "AAPL"}]

    def test_list_passes_through(self):
        assert as_list([1, 2]) == [1, 2]


class TestSelectExpirations:
    def test_keeps_only_window(self):
        as_of = date(2026, 7, 20)
        expirations = [
            date(2026, 7, 17),   # past -> dropped
            date(2026, 7, 24),   # 4 days -> kept
            date(2026, 9, 3),    # 45 days -> kept (boundary)
            date(2026, 9, 4),    # 46 days -> dropped
        ]
        assert select_expirations(expirations, as_of, 45) == [
            date(2026, 7, 24),
            date(2026, 9, 3),
        ]

    def test_same_day_expiration_kept(self):
        as_of = date(2026, 7, 20)
        assert select_expirations([as_of], as_of, 45) == [as_of]


class TestFilterStrikes:
    def test_window_is_inclusive_and_relative_to_spot(self):
        contracts = [{"strike": s} for s in (79, 80, 100, 120, 121)]
        kept = filter_strikes(contracts, spot=100.0, window_pct=0.20)
        assert [c["strike"] for c in kept] == [80, 100, 120]

    def test_missing_strike_dropped(self):
        assert filter_strikes([{"strike": None}, {}], spot=100.0, window_pct=0.20) == []


class TestTrimContract:
    def test_keeps_needed_fields_and_greeks_subset(self):
        raw = {
            "symbol": "AAPL260918C00230000",
            "description": "AAPL Sep 18 2026 $230.00 Call",  # dropped
            "strike": 230.0,
            "expiration_date": "2026-09-18",
            "option_type": "call",
            "bid": 5.1,
            "ask": 5.3,
            "last": 5.2,
            "volume": 1234,
            "open_interest": 5678,
            "root_symbol": "AAPL",  # dropped
            "greeks": {"delta": 0.45, "gamma": 0.02, "theta": -0.03, "vega": 0.12,
                       "mid_iv": 0.31, "smv_vol": 0.30, "rho": 0.01},
        }
        trimmed = trim_contract(raw)
        assert "description" not in trimmed
        assert "root_symbol" not in trimmed
        assert trimmed["volume"] == 1234
        assert trimmed["greeks"] == {
            "delta": 0.45, "gamma": 0.02, "theta": -0.03, "vega": 0.12, "mid_iv": 0.31,
        }

    def test_missing_greeks_yields_nulls(self):
        trimmed = trim_contract({"symbol": "X", "strike": 1.0})
        assert trimmed["greeks"] == {k: None for k in ("delta", "gamma", "theta", "vega", "mid_iv")}
