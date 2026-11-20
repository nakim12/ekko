-- Likely autofilled (PREREGISTRATION.md 4.4), autofill-sample matches only: a non-focal participant
-- whose role in the match differs from the role they played in at least
-- var('autofill_main_role_share') of their previous ranked games. Without such a main role they're
-- never counted as autofilled.
with history_roles as (
    select h.match_id, h.puuid, p.team_position as role
    from {{ ref('stg_q2_history_games') }} as h
    join {{ ref('stg_participants') }} as p on p.match_id = h.previous_match_id and p.puuid = h.puuid
    join {{ ref('int_matches') }} as m on m.match_id = h.previous_match_id
    where h.purpose = 'autofill' and not m.is_remake and p.team_position is not null
),

role_counts as (
    select match_id, puuid, role, count(*) as n
    from history_roles
    group by match_id, puuid, role
),

shares as (
    select *, n / sum(n) over (partition by match_id, puuid) as share, sum(n) over (partition by match_id, puuid) as n_games
    from role_counts
),

main_role as (
    select
        match_id,
        puuid,
        any_value(n_games) as n_previous_games,
        max(role) filter (where share >= {{ var('autofill_main_role_share') }}) as main_role
    from shares
    group by match_id, puuid
)

select
    p.match_id,
    p.puuid,
    p.role,
    m.main_role,
    coalesce(m.n_previous_games, 0) as n_previous_games,
    coalesce(m.main_role is not null and p.role <> m.main_role, false) as likely_autofilled
from {{ ref('int_q2_participants') }} as p
join {{ ref('stg_q2_matches') }} as q using (match_id)
left join main_role as m using (match_id, puuid)
where q.autofill_sample and not p.is_focal
