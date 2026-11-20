-- Grain: one row per qualified Q2 match per perspective. perspective = 'focal' is the H2/H2a
-- analysis; 'placebo' recomputes everything from a random non-focal participant's point of view
-- (PREREGISTRATION.md 7.2). The analysis reads this through ekko_analysis.data.
with perspectives as (
    select match_id, focal_puuid as puuid, 'focal' as perspective, focal_puuid from {{ ref('stg_q2_matches') }}
    where status = 'qualified'
    union all
    select match_id, placebo_puuid, 'placebo', focal_puuid from {{ ref('stg_q2_matches') }}
    where status = 'qualified'
),

me as (
    select v.*, p.team_id, p.win, p.ladder_position_at_match
    from perspectives as v
    join {{ ref('int_q2_participants') }} as p using (match_id, puuid)
),

teams as (
    select
        me.match_id,
        me.perspective,
        avg(o.ladder_position_at_match) filter (where o.team_id = me.team_id) as ally_strength_mean,
        avg(o.ladder_position_at_match) filter (where o.team_id <> me.team_id) as enemy_strength_mean,
        avg(o.ladder_position_looked_up) filter (where o.team_id = me.team_id) as ally_strength_mean_unadjusted,
        avg(o.ladder_position_looked_up) filter (where o.team_id <> me.team_id) as enemy_strength_mean_unadjusted,
        count(o.ladder_position_at_match) filter (where o.team_id = me.team_id) as n_allies_ranked,
        count(o.ladder_position_at_match) filter (where o.team_id <> me.team_id) as n_enemies_ranked
    from me
    join {{ ref('int_q2_participants') }} as o on o.match_id = me.match_id and o.puuid <> me.puuid
    group by all
),

autofill as (
    -- focal perspective only: the focal player's own role history isn't collected
    select
        me.match_id,
        count(*) filter (where a.likely_autofilled and p.team_id = me.team_id) as ally_autofilled,
        count(*) filter (where a.likely_autofilled and p.team_id <> me.team_id) as enemy_autofilled
    from me
    join {{ ref('int_q2_autofill') }} as a using (match_id)
    join {{ ref('int_q2_participants') }} as p on p.match_id = a.match_id and p.puuid = a.puuid
    where me.perspective = 'focal'
    group by all
)

select
    me.match_id as match_key,
    me.perspective,
    md5(me.puuid) as player_key,
    md5(me.focal_puuid) as focal_player_key,
    pl.sampled_tier,
    me.ladder_position_at_match as focal_ladder_position,
    t.ally_strength_mean,
    t.enemy_strength_mean,
    t.n_allies_ranked,
    t.n_enemies_ranked,
    case
        when t.n_allies_ranked >= {{ var('min_ranked_allies') }} and t.n_enemies_ranked >= {{ var('min_ranked_enemies') }}
            then t.ally_strength_mean - t.enemy_strength_mean
    end as strength_gap,
    t.ally_strength_mean_unadjusted - t.enemy_strength_mean_unadjusted as strength_gap_unadjusted,
    s.streak_state,
    s.n_previous_games,
    me.win as won_match,
    q.autofill_sample,
    case when q.autofill_sample and me.perspective = 'focal'
        then coalesce(af.ally_autofilled, 0) - coalesce(af.enemy_autofilled, 0) end as autofill_gap,
    q.lookup_delay_hours,
    m.patch,
    m.hour_local,
    isodow(m.game_start_local) as iso_day_of_week,
    m.date_key
from me
join {{ ref('stg_q2_matches') }} as q using (match_id)
join {{ ref('int_matches') }} as m using (match_id)
join teams as t on t.match_id = me.match_id and t.perspective = me.perspective
left join {{ ref('int_q2_streaks') }} as s on s.match_id = me.match_id and s.puuid = me.puuid and s.purpose = me.perspective
left join autofill as af on af.match_id = me.match_id and me.perspective = 'focal'
left join {{ ref('stg_players') }} as pl on pl.puuid = me.focal_puuid
