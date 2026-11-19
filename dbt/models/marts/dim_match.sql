select
    match_id as match_key,
    queue_id,
    patch,
    game_version,
    game_start_at,
    game_end_at,
    duration_seconds,
    is_remake,
    has_minute_mark,
    date_key,
    hour_local
from {{ ref('int_matches') }}
