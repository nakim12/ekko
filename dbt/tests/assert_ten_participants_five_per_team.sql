-- Every match has exactly 10 participants, 5 per team.
select match_id
from {{ ref('stg_participants') }}
group by match_id
having count(*) <> 10
    or count(*) filter (where team_id = 100) <> 5
    or count(*) filter (where team_id = 200) <> 5
