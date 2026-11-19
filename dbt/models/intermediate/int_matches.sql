-- Match-level flags (PREREGISTRATION.md 4.1) and local time for controls (US Central, section 5).
with early as (
    select match_id, bool_or(ended_in_early_surrender) as any_early_surrender
    from {{ ref('stg_participants') }}
    group by match_id
),

minute_mark as (
    -- The frame at the minute mark must really be from that minute; a game that ended just before
    -- has its end-of-game frame at the same index.
    select distinct match_id
    from {{ ref('stg_timeline_frames') }}
    where frame_index = {{ var('minute_mark') }} and timestamp_ms >= {{ var('minute_mark') }} * 60000
)

select
    m.*,
    m.duration_seconds < {{ var('remake_seconds') }} or coalesce(e.any_early_surrender, false) as is_remake,
    mm.match_id is not null as has_minute_mark,
    timezone('America/Chicago', m.game_start_at) as game_start_local,
    hour(timezone('America/Chicago', m.game_start_at)) as hour_local,
    strftime(timezone('America/Chicago', m.game_start_at), '%Y%m%d')::int as date_key
from {{ ref('stg_matches') }} as m
left join early as e using (match_id)
left join minute_mark as mm using (match_id)
