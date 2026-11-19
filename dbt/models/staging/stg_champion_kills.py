"""One row per CHAMPION_KILL timeline event.

Parsed in hash buckets with a typed schema for the same memory reason as stg_timeline_frames.
"""

import json

BUCKETS = 20


def model(dbt, session):
    dbt.config(materialized="table")
    dbt.source("raw", "timelines").create_view("_stg_champion_kills_src", replace=True)

    schema = json.dumps(
        [{"events": [{"type": "VARCHAR", "timestamp": "BIGINT", "killerId": "INTEGER", "victimId": "INTEGER"}]}]
    )
    session.sql(
        "create or replace temp table _stg_champion_kills ("
        "match_id varchar, timestamp_ms bigint, killer_participant_id int, victim_participant_id int)"
    )
    for k in range(BUCKETS):
        session.sql(f"""
            insert into _stg_champion_kills
            with frames as (
                select match_id, unnest(from_json(payload -> '$.info.frames', '{schema}')) as f
                from _stg_champion_kills_src
                where hash(match_id) % {BUCKETS} = {k}
            ),
            events as (
                select match_id, unnest(f.events) as e from frames
            )
            select match_id, e.timestamp, e.killerId, e.victimId
            from events
            where e.type = 'CHAMPION_KILL'
        """)
    return session.table("_stg_champion_kills")
