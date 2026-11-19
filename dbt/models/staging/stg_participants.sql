-- One row per player per match (10 per match).
with exploded as (
    select match_id, unnest(from_json(payload -> '$.info.participants', '["json"]')) as p
    from {{ source('raw', 'matches') }}
)
select
    match_id,
    (p ->> 'participantId')::int as participant_id,
    p ->> 'puuid' as puuid,
    (p ->> 'teamId')::int as team_id,
    nullif(p ->> 'teamPosition', '') as team_position,
    (p ->> 'championId')::int as champion_id,
    p ->> 'championName' as champion_name,
    (p ->> 'win')::boolean as win,
    (p ->> 'kills')::int as kills,
    (p ->> 'deaths')::int as deaths,
    (p ->> 'assists')::int as assists,
    (p ->> 'totalMinionsKilled')::int as minions_killed,
    (p ->> 'neutralMinionsKilled')::int as jungle_minions_killed,
    (p ->> 'goldEarned')::int as gold_earned,
    (p ->> 'totalDamageDealtToChampions')::int as damage_to_champions,
    (p ->> 'visionScore')::int as vision_score,
    (p ->> 'timePlayed')::int as time_played_seconds,
    (p ->> 'gameEndedInEarlySurrender')::boolean as ended_in_early_surrender,
    (p ->> 'gameEndedInSurrender')::boolean as ended_in_surrender
from exploded
