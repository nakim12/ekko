-- Grain: one row per focal player per match (remakes included, flagged).
-- q1_eligible marks the H1 analysis sample (PREREGISTRATION.md section 5).
with games as (
    select
        g.*,
        s.prev_match_id,
        s.session_id,
        s.game_number_in_session,
        s.break_minutes,
        s.break_bucket,
        s.prev_game_won,
        s.lost_prev,
        s.consecutive_losses_before,
        s.consecutive_wins_before,
        s.session_losses_before,
        z.gold_diff_14_z,
        z.cs_diff_14_z,
        z.xp_diff_14_z,
        z.deaths_before_14_z,
        z.perf_index,
        coalesce(duo.likely_duo, false) as likely_duo,
        not g.is_remake and not g.is_afk and g.has_minute_mark and g.has_lane_opponent as outcome_eligible
    from {{ ref('int_player_games') }} as g
    left join {{ ref('int_sessions') }} as s using (player_key, match_id)
    left join {{ ref('int_performance_scores') }} as z using (player_key, match_id)
    left join {{ ref('int_duo_flags') }} as duo using (player_key, match_id)
)

select
    -- keys
    g.player_key,
    g.match_id as match_key,
    g.champion_id as champion_key,
    g.date_key,
    g.role as role_key,
    -- outcome
    g.win,
    g.ended_in_early_surrender as early_surrender,
    g.is_remake as remake,
    -- performance
    g.kills,
    g.deaths,
    g.assists,
    g.cs_per_min,
    g.damage_share,
    g.vision_per_min,
    g.gold_diff_14,
    g.cs_diff_14,
    g.xp_diff_14,
    g.deaths_before_14,
    -- standardized (null unless outcome_eligible; also null when the tier x role x patch group has a single game)
    g.gold_diff_14_z,
    g.cs_diff_14_z,
    g.xp_diff_14_z,
    g.deaths_before_14_z,
    g.perf_index,
    -- context
    g.sampled_tier,
    g.tier_group,
    g.patch,
    g.hour_local,
    g.session_id,
    g.game_number_in_session,
    g.break_minutes as minutes_since_last_game,
    g.break_bucket,
    g.prev_game_won,
    g.lost_prev,
    g.consecutive_losses_before,
    g.consecutive_wins_before,
    g.session_losses_before,
    case
        when g.session_losses_before is null then null
        when g.session_losses_before >= 3 then '3+'
        else g.session_losses_before::varchar
    end as session_loss_run,
    case
        when g.prev_game_won is null then null
        when g.consecutive_losses_before >= 3 then 'L3+'
        when g.consecutive_losses_before = 2 then 'L2'
        when g.consecutive_wins_before >= 3 then 'W3+'
        when g.consecutive_wins_before = 2 then 'W2'
        else 'streak_1'
    end as streak_state,
    -- previous game's outcome for the lagged control (missing if it wasn't outcome-eligible)
    p.gold_diff_14_z as prev_gold_diff_14_z,
    g.prev_match_id is not null and p.gold_diff_14_z is null as prev_outcome_missing,
    -- sample flags
    g.is_afk as afk,
    g.likely_duo,
    g.has_lane_opponent,
    g.outcome_eligible,
    g.outcome_eligible and g.gold_diff_14_z is not null and g.lost_prev is not null as q1_eligible
from games as g
left join games as p
    on p.player_key = g.player_key and p.match_id = g.prev_match_id
