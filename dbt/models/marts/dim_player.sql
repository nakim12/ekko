-- One row per focal player. player_key is an MD5 of the PUUID; raw PUUIDs never reach the marts.
with roles as (
    select player_key, role, count(*) as n
    from {{ ref('int_player_games') }}
    where not is_remake and role is not null
    group by all
)

select
    g.player_key,
    any_value(g.sampled_tier) as sampled_tier,
    any_value(g.tier_group) as tier_group,
    any_value(pl.sampled_division) as sampled_division,
    (select arg_max(r.role, r.n) from roles as r where r.player_key = g.player_key) as main_role,
    count(*) filter (where not g.is_remake) as games_crawled
from {{ ref('int_player_games') }} as g
join {{ ref('stg_players') }} as pl using (puuid)
group by g.player_key
