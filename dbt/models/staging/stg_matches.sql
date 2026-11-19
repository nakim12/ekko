-- One row per match. Timestamps are UTC (timestamptz).
select
    match_id,
    payload ->> '$.info.platformId' as platform_id,
    (payload ->> '$.info.queueId')::int as queue_id,
    payload ->> '$.info.gameVersion' as game_version,
    regexp_extract(payload ->> '$.info.gameVersion', '^(\d+\.\d+)', 1) as patch,
    to_timestamp((payload ->> '$.info.gameStartTimestamp')::bigint / 1000.0) as game_start_at,
    to_timestamp((payload ->> '$.info.gameEndTimestamp')::bigint / 1000.0) as game_end_at,
    (payload ->> '$.info.gameDuration')::int as duration_seconds,
    payload ->> '$.info.endOfGameResult' as end_of_game_result
from {{ source('raw', 'matches') }}
