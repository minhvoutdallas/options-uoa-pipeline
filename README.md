# Options UOA Pipeline

An end-to-end, **$0/month** data pipeline that snapshots daily options-chain activity
for 10 liquid tickers, overlays company fundamentals, and flags **unusual options
activity (UOA)** on a dashboard.

Built as an analytics-engineering portfolio project: real external APIs, an ELT
warehouse pattern (raw → staging → marts), scheduled orchestration, tests at both
the Python and SQL layer, and dashboards with alerting — all on free tiers.

## Architecture

```
GitHub Actions (cron, 21:30 UTC weekdays)
 ├─ ingestion/ingest_options.py ──> Tradier API (chains + quotes) ──┐
 ├─ ingestion/ingest_fundamentals.py (weekly) ──> Yahoo Finance ────┼──> Neon Postgres: raw schema
 └─ dbt build ──> staging ──> marts (fct_option_activity, fct_uoa_flags)
                                        │
                          Grafana Cloud ┴── dashboards + UOA alert ──> Discord
```

| Layer | Tool | Free tier used |
|---|---|---|
| Options data | [Tradier](https://docs.tradier.com/) sandbox | 15-min delayed chains w/ volume, OI, greeks |
| Fundamentals | Yahoo Finance via `yfinance` | unofficial, fetched weekly |
| Warehouse | [Neon](https://neon.com) serverless Postgres | 0.5 GB storage, scale-to-zero |
| Orchestration | GitHub Actions cron | 2,000 min/month |
| Transform | dbt Core | open source |
| Dashboard | Grafana Cloud | 3 users, alerting included |

## The UOA rule

True tick-level "flow" (sweeps/blocks) isn't available on any free tier, so this
pipeline detects unusual activity by diffing **daily chain snapshots** against a
rolling baseline. For each ticker per day, aggregating near-the-money (NTM)
contracts — strikes within ±10% of spot — split by calls vs puts:

> **Flag** when NTM volume ≥ **3×** its trailing **10-trading-day** average
> **and** volume > open interest (new positions opening, not old ones closing).

All thresholds live in [`config/pipeline.yml`](config/pipeline.yml).

## Storage budget

Neon's free tier is 0.5 GB, so raw ingestion is deliberately trimmed:

- expirations limited to the next **45 days** (where UOA-relevant flow lives)
- strikes limited to **±20% of spot** (marts only need ±10%; the margin enables
  future skew analysis)
- contracts trimmed to ~10 fields + 5 greeks before landing as JSONB

That keeps raw growth to roughly 2–3 MB/day (~60–90 MB/month), with a planned
90-day raw retention prune. Marts are tiny (one row per ticker per day).

Because free historical chain data doesn't exist, **history accumulates from the
day ingestion starts** — the 10-day UOA baseline goes live after ~2 weeks of runs.

## Repo layout

```
config/pipeline.yml     tickers + all tunable thresholds
db/schema.sql           raw schema DDL (idempotent, applied at job start)
ingestion/              Python ingestion jobs (Tradier client, Neon loader)
tests/                  pytest unit tests for parsing/filtering logic
.github/workflows/      scheduled ingestion (cron + manual dispatch)
dbt/                    (phase 2) staging + marts models, tests, docs
```

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on mac/linux)
pip install -r requirements-dev.txt
copy .env.example .env          # then fill in TRADIER_TOKEN and DATABASE_URL
pytest                          # unit tests, no credentials needed
python -m ingestion.ingest_options --force   # full run against your Neon db
```

## Deploying

1. Create a free [Tradier developer account](https://documentation.tradier.com/) → copy the **sandbox** token.
2. Create a free [Neon](https://neon.com) project → copy the pooled connection string.
3. Push this repo to GitHub and add two **Actions secrets**: `TRADIER_TOKEN`, `DATABASE_URL`.
4. Trigger the `ingest-options` workflow manually once (Actions tab → Run workflow) to verify, then let the cron take over.

## Design decisions

- **Idempotent loads.** Every upsert keys on `(snapshot_date, …)`, so late, duplicate,
  or manually re-triggered runs are harmless — which is what makes GitHub Actions'
  imprecise cron acceptable for an EOD job.
- **Per-ticker failure isolation.** One ticker's API hiccup can't sink the other nine;
  the run is recorded as `partial` in `raw.ingest_runs` and CI still goes red.
- **Trim at ingestion, model in dbt.** Raw stays as JSONB (schema-on-read), but
  field/strike/expiry trimming happens in Python because the free-tier storage
  constraint is an ingestion concern, not a modeling one.
- **Calendar-aware.** The job checks Tradier's market calendar and no-ops on
  holidays instead of writing stale duplicate snapshots.

## Roadmap

- [x] **Phase 1 — Ingestion**: Tradier → Neon raw, scheduled + idempotent
- [ ] **Phase 2 — Modeling**: dbt staging/marts, UOA flag logic, source freshness tests; weekly fundamentals (yfinance)
- [ ] **Phase 3 — Serving**: Grafana dashboards + Discord alert on new UOA flags
- [ ] **Phase 4 — Hardening**: dbt build in CI on PRs (Neon branch per PR), dbt docs on GitHub Pages, 90-day raw retention job
