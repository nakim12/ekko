select
    match_id,
    status,
    focal_puuid,
    placebo_puuid,
    autofill_sample,
    game_end_at,
    ranks_looked_up_at,
    date_diff('second', game_end_at, ranks_looked_up_at) / 3600.0 as lookup_delay_hours,
    processed_at
from {{ source('raw', 'q2_matches') }}
