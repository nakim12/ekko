{{ config(enabled=var('phase', 0) | int == 1) }}
-- Every qualified Q2 match had all ranks looked up within 24 hours of it ending.
select match_key, perspective, lookup_delay_hours
from {{ ref('fct_match_team_strength') }}
where lookup_delay_hours > 24 or lookup_delay_hours < 0
