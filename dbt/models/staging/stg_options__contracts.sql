-- One row per option contract per snapshot day: the JSONB contract arrays in
-- raw.option_chains exploded and typed. This is the only place the pipeline
-- pays the JSONB-parsing cost; everything downstream sees real columns.

with chains as (

    select * from {{ source('raw', 'option_chains') }}

),

contracts as (

    select
        chains.snapshot_date,
        chains.underlying,
        chains.expiration,
        chains.spot_price,
        contract ->> 'symbol'                                    as contract_symbol,
        (contract ->> 'strike')::numeric                         as strike,
        contract ->> 'option_type'                               as option_type,
        (contract ->> 'bid')::numeric                            as bid,
        (contract ->> 'ask')::numeric                            as ask,
        (contract ->> 'last')::numeric                           as last_price,
        coalesce((contract ->> 'volume')::bigint, 0)             as volume,
        coalesce((contract ->> 'open_interest')::bigint, 0)      as open_interest,
        (contract -> 'greeks' ->> 'delta')::numeric              as delta,
        (contract -> 'greeks' ->> 'gamma')::numeric              as gamma,
        (contract -> 'greeks' ->> 'theta')::numeric              as theta,
        (contract -> 'greeks' ->> 'vega')::numeric               as vega,
        (contract -> 'greeks' ->> 'mid_iv')::numeric             as implied_vol
    from chains
    cross join lateral jsonb_array_elements(chains.payload) as contract

)

select
    *,
    (expiration - snapshot_date)                     as days_to_expiration,
    strike / nullif(spot_price, 0) - 1               as moneyness
from contracts
