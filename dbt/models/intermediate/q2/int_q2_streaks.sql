-- Streak state just before each Q2 match for the focal and the placebo player (PREREGISTRATION.md
-- 4.3): consecutive identical results immediately before the match, from their previous ranked
-- games. Remakes and games that weren't stored are skipped.
with results as (
    select h.match_id, h.puuid, h.purpose, h.recency, p.win
    from {{ ref('stg_q2_history_games') }} as h
    join {{ ref('stg_participants') }} as p on p.match_id = h.previous_match_id and p.puuid = h.puuid
    join {{ ref('int_matches') }} as m on m.match_id = h.previous_match_id
    where h.purpose in ('focal', 'placebo') and not m.is_remake
),

sequences as (
    select match_id, puuid, purpose, list(win order by recency) as wins
    from results
    group by all
),

runs as (
    select
        *,
        wins[1] as prev_won,
        -- length of the leading run of results equal to the most recent one
        coalesce(nullif(list_position(list_transform(wins, lambda w: w <> wins[1]), true), 0) - 1, len(wins))
            as run_length
    from sequences
)

select
    match_id,
    puuid,
    purpose,
    len(wins) as n_previous_games,
    prev_won,
    run_length,
    case
        when not prev_won and run_length >= 3 then 'L3+'
        when not prev_won and run_length = 2 then 'L2'
        when prev_won and run_length >= 3 then 'W3+'
        when prev_won and run_length = 2 then 'W2'
        else 'streak_1'
    end as streak_state
from runs
