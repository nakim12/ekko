-- Focal players and the league-v4 entry they were sampled from.
select
    puuid,
    upper(tier) as sampled_tier,
    division as sampled_division,
    league_points as sampled_league_points,
    wins as sampled_wins,
    losses as sampled_losses
from {{ source('raw', 'players') }}
