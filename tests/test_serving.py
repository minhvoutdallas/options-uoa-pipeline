from datetime import date

import pytest

from scripts.deploy_grafana import datasource_payload
from scripts.prune_raw import cutoff_date
from scripts.send_uoa_alerts import format_alert


def test_discord_alert_is_readable_and_disables_mentions():
    payload = format_alert(
        {
            "snapshot_date": date(2026, 7, 22),
            "underlying": "AAPL",
            "option_type": "call",
            "ntm_volume": 12_345,
            "ntm_open_interest": 2_000,
            "baseline_ntm_volume": 3_000,
            "volume_ratio": 4.115,
        }
    )
    assert payload["allowed_mentions"] == {"parse": []}
    description = payload["embeds"][0]["description"]
    assert "AAPL CALL" in description
    assert "12,345" in description
    assert "4.1x" in description


def test_retention_cutoff():
    assert cutoff_date(date(2026, 7, 23), 90) == date(2026, 4, 24)
    with pytest.raises(ValueError):
        cutoff_date(date(2026, 7, 23), 0)


def test_grafana_datasource_parses_encoded_credentials():
    payload = datasource_payload(
        "postgresql://u%40ser:p%2Fass@ep-example.neon.tech/neondb?sslmode=require"
    )
    assert payload["url"] == "ep-example.neon.tech:5432"
    assert payload["user"] == "u@ser"
    assert payload["secureJsonData"]["password"] == "p/ass"
    assert payload["jsonData"]["sslmode"] == "require"
