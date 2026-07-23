-- Raw landing zone. Loads are idempotent: re-running a day's ingestion
-- overwrites that day's rows via the primary-key upserts in ingestion/db.py.
-- dbt (phase 2) reads from here and never writes back.

CREATE SCHEMA IF NOT EXISTS raw;

-- One row per underlying per trading day: the full Tradier quote object.
CREATE TABLE IF NOT EXISTS raw.underlying_quotes (
    snapshot_date  date        NOT NULL,
    symbol         text        NOT NULL,
    payload        jsonb       NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, symbol)
);

-- One row per (underlying, expiration) per trading day. payload is a JSONB
-- array of contract objects, trimmed at ingestion to the fields the marts
-- need (see ingestion/ingest_options.py) to respect Neon's 0.5 GB free tier.
CREATE TABLE IF NOT EXISTS raw.option_chains (
    snapshot_date   date        NOT NULL,
    underlying      text        NOT NULL,
    expiration      date        NOT NULL,
    spot_price      numeric     NOT NULL,
    payload         jsonb       NOT NULL,
    contract_count  integer     NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, underlying, expiration)
);

-- One row per ticker per weekly run: trimmed yfinance company snapshot
-- (see ingestion/ingest_fundamentals.py for the field list).
CREATE TABLE IF NOT EXISTS raw.fundamentals (
    snapshot_date  date        NOT NULL,
    symbol         text        NOT NULL,
    payload        jsonb       NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, symbol)
);

-- Lightweight run log for observability: one row per job invocation.
CREATE TABLE IF NOT EXISTS raw.ingest_runs (
    run_id        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job           text        NOT NULL,
    snapshot_date date        NOT NULL,
    started_at    timestamptz NOT NULL,
    finished_at   timestamptz,
    status        text        NOT NULL DEFAULT 'running',
    detail        jsonb
);

-- Delivery ledger for idempotent Discord notifications. A flag is marked only
-- after Discord accepts it, so workflow retries cannot duplicate alerts.
CREATE TABLE IF NOT EXISTS raw.uoa_alert_deliveries (
    snapshot_date date        NOT NULL,
    underlying   text        NOT NULL,
    option_type  text        NOT NULL,
    alerted_at   timestamptz NOT NULL DEFAULT now(),
    payload      jsonb       NOT NULL,
    PRIMARY KEY (snapshot_date, underlying, option_type)
);
