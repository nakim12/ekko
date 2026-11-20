-- One row per focal player per day (UTC) with a snapshot.
select
    md5(puuid) as player_key,
    snapshot_date,
    found as ranked,
    tier,
    division,
    league_points,
    ladder_position,
    wins,
    losses
from {{ ref('stg_rank_snapshots') }}
qualify row_number() over (partition by puuid, snapshot_date order by snapshot_at desc) = 1
