-- Daily option-activity rollup: one row per (day, underlying, call/put side).
-- The full ±20% ingested strike window is aggregated for context columns, and
-- the ±{{ var('ntm_pct') * 100 }}% near-the-money slice — where the UOA rule
-- looks — gets its own columns.

with contracts as (

    select
        *,
        abs(moneyness) <= {{ var('ntm_pct') }} as is_ntm
    from {{ ref('stg_options__contracts') }}

)

select
    snapshot_date,
    underlying,
    option_type,
    max(spot_price)                                          as spot_price,

    count(*)                                                 as contracts,
    sum(volume)                                              as volume,
    sum(open_interest)                                       as open_interest,

    count(*) filter (where is_ntm)                           as ntm_contracts,
    coalesce(sum(volume) filter (where is_ntm), 0)           as ntm_volume,
    coalesce(sum(open_interest) filter (where is_ntm), 0)    as ntm_open_interest,

    -- volume-weighted implied vol of the NTM slice (null until volume shows up)
    sum(volume * implied_vol) filter (where is_ntm and implied_vol is not null)
        / nullif(sum(volume) filter (where is_ntm and implied_vol is not null), 0)
                                                             as ntm_vw_implied_vol
from contracts
group by snapshot_date, underlying, option_type
