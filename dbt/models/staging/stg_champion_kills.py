"""One row per CHAMPION_KILL timeline event.

Parsed in match_id ranges with a typed schema for the same memory reason as stg_timeline_frames.
"""

import json

CHUNK = 200  # timelines parsed per batch


def id_ranges(session, relation: str):
    """Consecutive (first, last) match_id ranges of CHUNK timelines each. Parquet segments are
    written roughly in match_id order, so a range filter lets DuckDB skip most of the files."""
    ids = [r[0] for r in session.sql(f"select match_id from {relation} order by match_id").fetchall()]
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start : start + CHUNK]
        yield chunk[0], chunk[-1]


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
    for lo, hi in id_ranges(session, "_stg_champion_kills_src"):
        session.sql(f"""
            insert into _stg_champion_kills
            with frames as (
                select match_id, unnest(from_json(payload -> '$.info.frames', '{schema}')) as f
                from _stg_champion_kills_src
                where match_id between '{lo}' and '{hi}'
            ),
            events as (
                select match_id, unnest(f.events) as e from frames
            )
            select match_id, e.timestamp, e.killerId, e.victimId
            from events
            where e.type = 'CHAMPION_KILL'
        """)
    return session.table("_stg_champion_kills")
