-- Latest fundamentals snapshot per ticker, plus the next known earnings date —
-- the overlay that gives a UOA flag context (unusual call buying the week
-- before earnings reads very differently from flow in a quiet week).

with latest as (

    select distinct on (symbol) *
    from {{ ref('stg_fundamentals') }}
    order by symbol, snapshot_date desc

)

select
    latest.symbol,
    latest.company_name,
    latest.quote_type,
    latest.sector,
    latest.industry,
    latest.market_cap,
    latest.trailing_pe,
    latest.forward_pe,
    latest.trailing_eps,
    latest.price_to_sales,
    latest.profit_margin,
    latest.revenue_growth,
    latest.beta,
    latest.shares_outstanding,
    latest.short_pct_of_float,
    latest.dividend_yield,
    upcoming.next_earnings_date,
    latest.snapshot_date        as as_of_date
from latest
left join lateral (
    select min((earnings_date #>> '{}')::date) as next_earnings_date
    from jsonb_array_elements(latest.earnings_dates) as earnings_date
    where (earnings_date #>> '{}')::date >= latest.snapshot_date
) as upcoming on true
