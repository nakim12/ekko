-- Per participant: gold, XP and CS at the minute mark, and deaths before it. Only for games that
-- reached the minute mark.
with frame as (
    select match_id, participant_id, total_gold, xp, minions_killed + jungle_minions_killed as cs
    from {{ ref('stg_timeline_frames') }}
    where frame_index = {{ var('minute_mark') }} and timestamp_ms >= {{ var('minute_mark') }} * 60000
),

deaths as (
    select match_id, victim_participant_id as participant_id, count(*) as deaths
    from {{ ref('stg_champion_kills') }}
    where timestamp_ms < {{ var('minute_mark') }} * 60000
    group by all
)

select
    f.match_id,
    f.participant_id,
    f.total_gold as gold_at_mark,
    f.xp as xp_at_mark,
    f.cs as cs_at_mark,
    coalesce(d.deaths, 0) as deaths_before_mark
from frame as f
left join deaths as d using (match_id, participant_id)
