"""Load pipeline settings from config/pipeline.yml plus environment variables.

Secrets (Tradier token, Neon URL) come from the environment — locally via a
.env file, in CI via GitHub Actions secrets. Everything tunable lives in
config/pipeline.yml so behavior changes never require code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline.yml"

TRADIER_BASE_URLS = {
    "sandbox": "https://sandbox.tradier.com/v1",
    "production": "https://api.tradier.com/v1",
}


@dataclass(frozen=True)
class Settings:
    tickers: list[str]
    max_expiration_days: int
    strike_window_pct: float
    tradier_token: str = field(repr=False)
    tradier_base_url: str
    database_url: str = field(repr=False)


def load_settings(config_path: Path = CONFIG_PATH) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    token = os.environ.get("TRADIER_TOKEN")
    if not token:
        raise RuntimeError("TRADIER_TOKEN is not set (see .env.example)")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")

    env = os.environ.get("TRADIER_ENV", "sandbox")
    if env not in TRADIER_BASE_URLS:
        raise RuntimeError(f"TRADIER_ENV must be one of {sorted(TRADIER_BASE_URLS)}, got {env!r}")

    return Settings(
        tickers=list(cfg["tickers"]),
        max_expiration_days=int(cfg["options"]["max_expiration_days"]),
        strike_window_pct=float(cfg["options"]["strike_window_pct"]),
        tradier_token=token,
        tradier_base_url=TRADIER_BASE_URLS[env],
        database_url=database_url,
    )
