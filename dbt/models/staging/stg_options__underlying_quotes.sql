-- One row per underlying per snapshot day, typed out of the raw Tradier quote.

select
    snapshot_date,
    symbol,
    (payload ->> 'last')::numeric               as last_price,
    (payload ->> 'prevclose')::numeric          as prev_close,
    (payload ->> 'change_percentage')::numeric  as change_pct,
    (payload ->> 'volume')::bigint              as share_volume,
    (payload ->> 'average_volume')::bigint      as avg_share_volume,
    (payload ->> 'week_52_high')::numeric       as week_52_high,
    (payload ->> 'week_52_low')::numeric        as week_52_low,
    ingested_at
from {{ source('raw', 'underlying_quotes') }}
