-- One row per previous game in a Q2 history list. recency 1 is the game right before the Q2 match
-- (match-v5 returns IDs newest first).
select
    match_id,
    puuid,
    purpose,
    unnest(previous_match_ids) as previous_match_id,
    generate_subscripts(previous_match_ids, 1) as recency
from {{ source('raw', 'q2_history') }}
