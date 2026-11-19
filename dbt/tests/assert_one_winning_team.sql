-- Exactly one team wins, and teammates agree on the result.
with teams as (
    select match_id, team_id, bool_and(win) as all_won, bool_or(win) as any_won
    from {{ ref('stg_participants') }}
    group by all
)
select match_id
from teams
group by match_id
having count(*) filter (where all_won) <> 1
    or count(*) filter (where any_won and not all_won) > 0
