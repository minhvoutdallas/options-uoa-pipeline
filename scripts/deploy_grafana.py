"""Upsert the Neon data source and UOA dashboard into Grafana.

This uses Grafana's HTTP API instead of keeping Terraform state, making the
manual GitHub Actions deployment repeatable and safe.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = PROJECT_ROOT / "grafana" / "dashboard.json"
DATASOURCE_UID = "neon-uoa"


def datasource_payload(database_url: str) -> dict:
    url = urlsplit(database_url)
    if not (url.hostname and url.username and url.password and url.path.lstrip("/")):
        raise SystemExit("DATABASE_URL must look like postgresql://user:pass@host/dbname")
    return {
        "uid": DATASOURCE_UID,
        "name": "Neon Options UOA",
        "type": "postgres",
        "access": "proxy",
        "url": f"{url.hostname}:{url.port or 5432}",
        "user": unquote(url.username),
        "database": url.path.lstrip("/"),
        "basicAuth": False,
        "jsonData": {
            "database": url.path.lstrip("/"),
            "sslmode": "require",
            "postgresVersion": 1500,
            "timescaledb": False,
        },
        "secureJsonData": {"password": unquote(url.password)},
    }


def request(session: requests.Session, method: str, url: str, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    grafana_url = os.environ.get("GRAFANA_URL", "").rstrip("/")
    token = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN")
    database_url = os.environ.get("DATABASE_URL")
    if not grafana_url:
        raise SystemExit("GRAFANA_URL is not set")
    if not token:
        raise SystemExit("GRAFANA_SERVICE_ACCOUNT_TOKEN is not set")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")

    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )

    data_source = datasource_payload(database_url)
    lookup = session.get(
        f"{grafana_url}/api/datasources/uid/{DATASOURCE_UID}", timeout=30
    )
    if lookup.status_code == 404:
        request(session, "POST", f"{grafana_url}/api/datasources", json=data_source)
        action = "created"
    else:
        lookup.raise_for_status()
        request(
            session,
            "PUT",
            f"{grafana_url}/api/datasources/uid/{DATASOURCE_UID}",
            json=data_source,
        )
        action = "updated"

    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    result = request(
        session,
        "POST",
        f"{grafana_url}/api/dashboards/db",
        json={"dashboard": dashboard, "folderUid": "", "overwrite": True},
    ).json()
    print(f"Grafana data source {action}; dashboard: {grafana_url}{result['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
