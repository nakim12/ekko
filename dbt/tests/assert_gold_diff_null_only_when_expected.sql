-- gold_diff_14 is missing only for remakes, games that ended before minute 14, or games without a
-- unique lane opponent.
select player_key, match_key
from {{ ref('fct_player_games') }} as f
join {{ ref('dim_match') }} as m using (match_key)
where f.gold_diff_14 is null
    and not f.remake
    and m.has_minute_mark
    and f.has_lane_opponent
