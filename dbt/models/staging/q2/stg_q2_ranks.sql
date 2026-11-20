select
    match_id,
    puuid,
    looked_up_at,
    found,
    tier,
    rank as division,
    league_points,
    {{ ladder_position('tier', 'rank', 'league_points') }} as ladder_position
from {{ source('raw', 'q2_ranks') }}
