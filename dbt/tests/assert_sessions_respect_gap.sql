-- No session contains a break at or above the threshold, and every such break starts a new session.
select player_key, match_key
from {{ ref('fct_player_games') }}
where not remake
    and (
        (game_number_in_session > 1 and minutes_since_last_game >= {{ var('session_gap_minutes') }})
        or (game_number_in_session = 1 and minutes_since_last_game < {{ var('session_gap_minutes') }})
    )
