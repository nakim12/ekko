-- Which matches make up each focal player's crawled history.
select distinct puuid, match_id
from {{ source('raw', 'player_match_ids') }}
