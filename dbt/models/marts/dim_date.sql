-- Every date (US Central) from the first to the last match.
with bounds as (
    select min(game_start_local)::date as first_day, max(game_start_local)::date as last_day
    from {{ ref('int_matches') }}
)

select
    strftime(d, '%Y%m%d')::int as date_key,
    d::date as date,
    dayname(d) as day_of_week,
    isodow(d) as iso_day_of_week,
    isodow(d) >= 6 as is_weekend
from bounds, generate_series(first_day, last_day, interval 1 day) as t(d)
