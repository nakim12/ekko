"""One row per participant per timeline frame.

Frames are 60 s apart, so frame_index n is minute n (the last frame is the end of the game).

Timelines are ~0.8 MB of JSON each, and DuckDB parses up to 2,048 rows per chunk, so parsing the whole
table at once runs out of memory. This model parses a hash bucket of matches at a time instead, with a
typed from_json schema so only the needed fields are materialized.
"""

import json

BUCKETS = 20
FIELDS = {
    "totalGold": "total_gold",
    "xp": "xp",
    "level": "level",
    "minionsKilled": "minions_killed",
    "jungleMinionsKilled": "jungle_minions_killed",
}


def model(dbt, session):
    dbt.config(materialized="table")
    dbt.source("raw", "timelines").create_view("_stg_timeline_frames_src", replace=True)

    frame_type = {f: "INTEGER" for f in FIELDS}
    schema = json.dumps(
        [{"timestamp": "BIGINT", "participantFrames": {str(i): frame_type for i in range(1, 11)}}]
    )
    participants = ", ".join(f'f.participantFrames."{i}"' for i in range(1, 11))
    columns = ", ".join(f"(s).{src}::int as {dst}" for src, dst in FIELDS.items())

    session.sql(
        "create or replace temp table _stg_timeline_frames ("
        "match_id varchar, frame_index int, timestamp_ms bigint, participant_id int, "
        + ", ".join(f"{dst} int" for dst in FIELDS.values())
        + ")"
    )
    for k in range(BUCKETS):
        session.sql(f"""
            insert into _stg_timeline_frames
            with parsed as (
                select match_id, from_json(payload -> '$.info.frames', '{schema}') as frames
                from _stg_timeline_frames_src
                where hash(match_id) % {BUCKETS} = {k}
            ),
            per_frame as (
                select match_id, unnest(frames) as f, generate_subscripts(frames, 1) - 1 as frame_index
                from parsed
            ),
            per_participant as (
                select
                    match_id,
                    frame_index,
                    f.timestamp as timestamp_ms,
                    unnest([{participants}]) as s,
                    generate_subscripts([{participants}], 1) as participant_id
                from per_frame
            )
            select match_id, frame_index, timestamp_ms, participant_id, {columns}
            from per_participant
        """)
    return session.table("_stg_timeline_frames")
