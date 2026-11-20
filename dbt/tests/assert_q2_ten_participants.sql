{{ config(enabled=var('phase', 0) | int == 1) }}
-- Every qualified Q2 match has 10 participants, 10 rank lookups and one focal player.
select match_id
from {{ ref('int_q2_participants') }}
group by match_id
having count(*) <> 10 or count(*) filter (where ranked is not null) <> 10 or count(*) filter (where is_focal) <> 1
