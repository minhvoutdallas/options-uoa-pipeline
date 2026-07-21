-- The UOA rule, applied. One row per (day, underlying, side) with the trailing
-- baseline and an is_uoa flag:
--
--   flag when NTM volume >= {{ var('uoa_volume_multiple') }}x its trailing
--   {{ var('uoa_baseline_days') }}-trading-day average AND NTM volume > NTM
--   open interest (new positioning, not closing flow).
--
-- All rows are kept (not just flagged ones) so Grafana can chart volume vs
-- baseline over time; a full baseline window is required before flagging, so
-- the first {{ var('uoa_baseline_days') }} trading days never flag.

with activity as (

    select * from {{ ref('fct_option_activity') }}

),

baselined as (

    select
        *,
        avg(ntm_volume) over trailing_baseline   as baseline_ntm_volume,
        count(*) over trailing_baseline          as baseline_days_available
    from activity
    window trailing_baseline as (
        partition by underlying, option_type
        order by snapshot_date
        rows between {{ var('uoa_baseline_days') }} preceding and 1 preceding
    )

)

select
    snapshot_date,
    underlying,
    option_type,
    spot_price,
    ntm_volume,
    ntm_open_interest,
    ntm_vw_implied_vol,
    baseline_ntm_volume,
    baseline_days_available,
    ntm_volume / nullif(baseline_ntm_volume, 0)              as volume_ratio,
    (
        baseline_days_available >= {{ var('uoa_baseline_days') }}
        and ntm_volume >= {{ var('uoa_volume_multiple') }} * baseline_ntm_volume
        and ntm_volume > ntm_open_interest
    )                                                        as is_uoa
from baselined
