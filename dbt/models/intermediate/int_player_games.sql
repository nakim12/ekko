-- Focal player-games with lane-opponent comparisons at the minute mark. Only matches in the
-- player's crawled history count (stg_player_match_ids), not Q2 or placebo matches they appear in.
with participants as (
    select
        *,
        damage_to_champions / nullif(sum(damage_to_champions) over (partition by match_id, team_id), 0) as damage_share
    from {{ ref('stg_participants') }}
)

select
    p.match_id,
    p.puuid,
    md5(p.puuid) as player_key,
    pl.sampled_tier,
    case
        when pl.sampled_tier in ('IRON', 'BRONZE', 'SILVER') then 'iron_silver'
        when pl.sampled_tier in ('GOLD', 'PLATINUM') then 'gold_platinum'
        else 'emerald_plus'
    end as tier_group,
    p.participant_id,
    p.team_id,
    p.team_position as role,
    p.champion_id,
    p.win,
    p.ended_in_early_surrender,
    m.is_remake,
    m.has_minute_mark,
    m.patch,
    m.game_start_at,
    m.game_end_at,
    m.duration_seconds,
    m.hour_local,
    m.date_key,
    p.kills,
    p.deaths,
    p.assists,
    (p.minions_killed + p.jungle_minions_killed) / (m.duration_seconds / 60.0) as cs_per_min,
    p.damage_share,
    p.vision_score / (m.duration_seconds / 60.0) as vision_per_min,
    lo.opponent_participant_id,
    lo.opponent_participant_id is not null as has_lane_opponent,
    f.gold_at_mark - o.gold_at_mark as gold_diff_14,
    f.cs_at_mark - o.cs_at_mark as cs_diff_14,
    f.xp_at_mark - o.xp_at_mark as xp_diff_14,
    f.deaths_before_mark as deaths_before_14,
    coalesce(
        m.has_minute_mark and (f.xp_at_mark < {{ var('afk_xp_at_14') }} or o.xp_at_mark < {{ var('afk_xp_at_14') }}),
        false
    ) as is_afk
from participants as p
join {{ ref('stg_players') }} as pl using (puuid)
join {{ ref('stg_player_match_ids') }} as h using (puuid, match_id)
join {{ ref('int_matches') }} as m using (match_id)
left join {{ ref('int_lane_opponents') }} as lo using (match_id, participant_id)
left join {{ ref('int_participant_minute_mark') }} as f
    on f.match_id = p.match_id and f.participant_id = p.participant_id
left join {{ ref('int_participant_minute_mark') }} as o
    on o.match_id = p.match_id and o.participant_id = lo.opponent_participant_id
