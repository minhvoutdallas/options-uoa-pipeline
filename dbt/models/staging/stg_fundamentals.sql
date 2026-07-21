-- One row per symbol per weekly snapshot, typed out of the trimmed yfinance
-- payload. ETFs (SPY, QQQ) carry nulls for the equity-only fields.

select
    snapshot_date,
    symbol,
    payload ->> 'longName'                                  as company_name,
    payload ->> 'quoteType'                                 as quote_type,
    payload ->> 'sector'                                    as sector,
    payload ->> 'industry'                                  as industry,
    (payload ->> 'marketCap')::numeric                      as market_cap,
    (payload ->> 'trailingPE')::numeric                     as trailing_pe,
    (payload ->> 'forwardPE')::numeric                      as forward_pe,
    (payload ->> 'trailingEps')::numeric                    as trailing_eps,
    (payload ->> 'priceToSalesTrailing12Months')::numeric   as price_to_sales,
    (payload ->> 'profitMargins')::numeric                  as profit_margin,
    (payload ->> 'revenueGrowth')::numeric                  as revenue_growth,
    (payload ->> 'beta')::numeric                           as beta,
    (payload ->> 'sharesOutstanding')::numeric              as shares_outstanding,
    (payload ->> 'shortPercentOfFloat')::numeric            as short_pct_of_float,
    (payload ->> 'dividendYield')::numeric                  as dividend_yield,
    payload -> 'earnings_dates'                             as earnings_dates,
    ingested_at
from {{ source('raw', 'fundamentals') }}
