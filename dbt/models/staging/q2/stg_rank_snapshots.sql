select
    puuid,
    snapshot_at,
    timezone('UTC', snapshot_at)::date as snapshot_date,
    found,
    tier,
    rank as division,
    league_points,
    wins,
    losses,
    {{ ladder_position('tier', 'rank', 'league_points') }} as ladder_position
from {{ source('raw', 'rank_snapshots') }}
