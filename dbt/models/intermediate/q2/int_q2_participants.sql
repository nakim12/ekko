-- All 10 participants of each qualified Q2 match with their rank at match time
-- (PREREGISTRATION.md 4.4): the lookup came after the match, so its result is removed by taking
-- var('match_lp_adjustment') LP from each winner and giving it back to each loser.
select
    q.match_id,
    p.puuid,
    p.team_id,
    p.team_position as role,
    p.win,
    p.puuid = q.focal_puuid as is_focal,
    p.puuid = q.placebo_puuid as is_placebo,
    r.found as ranked,
    r.ladder_position as ladder_position_looked_up,
    r.ladder_position + case when p.win then -1 else 1 end * {{ var('match_lp_adjustment') }}
        as ladder_position_at_match
from {{ ref('stg_q2_matches') }} as q
join {{ ref('stg_participants') }} as p using (match_id)
left join {{ ref('stg_q2_ranks') }} as r using (match_id, puuid)
where q.status = 'qualified'
