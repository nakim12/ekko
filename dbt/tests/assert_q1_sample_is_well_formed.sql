-- Every H1-sample row has a previous game in the same session and a standardized outcome.
select player_key, match_key
from {{ ref('fct_player_games') }}
where q1_eligible
    and (lost_prev is null or gold_diff_14_z is null or game_number_in_session < 2 or afk or remake)
