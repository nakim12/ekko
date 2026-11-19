-- Game sequence per focal player, remakes excluded (PREREGISTRATION.md 4.1, 4.3).
-- break = previous game's end to this game's start. A session breaks at a gap of
-- var('session_gap_minutes') or more.
with games as (
    select player_key, match_id, game_start_at, game_end_at, win
    from {{ ref('int_player_games') }}
    where not is_remake
),

lagged as (
    select
        *,
        lag(match_id) over w as prev_match_id,
        lag(win) over w as prev_win,
        date_diff('second', lag(game_end_at) over w, game_start_at) / 60.0 as break_minutes
    from games
    window w as (partition by player_key order by game_start_at, match_id)
),

flagged as (
    select
        *,
        prev_match_id is null or break_minutes >= {{ var('session_gap_minutes') }} as starts_session
    from lagged
),

numbered as (
    select
        *,
        sum(starts_session::int) over w as session_number,
        -- a new result run starts when the result changes; a new in-session run also starts with each session
        sum((prev_win is null or win <> prev_win)::int) over w as run_number,
        sum((starts_session or win <> prev_win)::int) over w as session_run_number
    from flagged
    window w as (partition by player_key order by game_start_at, match_id rows unbounded preceding)
),

positioned as (
    select
        *,
        row_number() over (partition by player_key, session_number order by game_start_at, match_id) as game_number_in_session,
        row_number() over (partition by player_key, run_number order by game_start_at, match_id) as run_position,
        row_number() over (partition by player_key, session_run_number order by game_start_at, match_id) as session_run_position
    from numbered
),

with_prev as (
    select
        *,
        lag(run_position) over w as prev_run_position,
        lag(session_run_position) over w as prev_session_run_position
    from positioned
    window w as (partition by player_key order by game_start_at, match_id)
)

select
    player_key,
    match_id,
    prev_match_id,
    player_key || '-' || session_number as session_id,
    game_number_in_session,
    break_minutes,
    case
        when break_minutes is null then null
        when break_minutes < 15 then 'lt_15m'
        when break_minutes < 60 then '15_60m'
        when break_minutes < 360 then '1_6h'
        when break_minutes < 1440 then '6_24h'
        else 'gt_24h'
    end as break_bucket,
    prev_win as prev_game_won,
    -- across sessions
    case when prev_win is null then null when not prev_win then prev_run_position else 0 end as consecutive_losses_before,
    case when prev_win is null then null when prev_win then prev_run_position else 0 end as consecutive_wins_before,
    -- within the session (null for the first game of a session)
    case when starts_session then null else not prev_win end as lost_prev,
    case when starts_session then null when not prev_win then prev_session_run_position else 0 end as session_losses_before
from with_prev
