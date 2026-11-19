-- Lane opponent: the enemy with the same teamPosition, only when each team has exactly one player
-- in that position (PREREGISTRATION.md 4.1). Participants without a unique match have no row.
with p as (
    select match_id, participant_id, team_id, team_position
    from {{ ref('stg_participants') }}
    where team_position is not null
),

position_counts as (
    select
        match_id,
        team_position,
        count(*) filter (where team_id = 100) as n_blue,
        count(*) filter (where team_id = 200) as n_red
    from p
    group by all
)

select a.match_id, a.participant_id, b.participant_id as opponent_participant_id
from p as a
join p as b
    on a.match_id = b.match_id and a.team_position = b.team_position and a.team_id <> b.team_id
join position_counts as c
    on c.match_id = a.match_id and c.team_position = a.team_position
where c.n_blue = 1 and c.n_red = 1
