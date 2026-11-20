-- Duo-queue sensitivity (PREREGISTRATION.md 8): a focal game is a likely duo if any teammate also
-- appears on the focal player's team in 3 or more of the player's other crawled games.
with focal as (
    select player_key, puuid, match_id, team_id
    from {{ ref('int_player_games') }}
),

teammates as (
    select f.player_key, f.match_id, p.puuid as teammate
    from focal as f
    join {{ ref('stg_participants') }} as p
        on p.match_id = f.match_id and p.team_id = f.team_id and p.puuid <> f.puuid
),

repeats as (
    select player_key, teammate, count(distinct match_id) as n_games
    from teammates
    group by all
)

select
    t.player_key,
    t.match_id,
    -- n_games counts this game too, so "3 or more other games" is 4 or more in total
    coalesce(max(r.n_games) >= 4, false) as likely_duo
from teammates as t
join repeats as r using (player_key, teammate)
group by all
