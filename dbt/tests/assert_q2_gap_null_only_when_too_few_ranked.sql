{{ config(enabled=var('phase', 0) | int == 1) }}
-- strength_gap is missing exactly when too few teammates or enemies have a rank.
select match_key, perspective
from {{ ref('fct_match_team_strength') }}
where (strength_gap is null)
    <> (n_allies_ranked < {{ var('min_ranked_allies') }} or n_enemies_ranked < {{ var('min_ranked_enemies') }})
