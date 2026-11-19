"""One row per participant per timeline frame.

Frames are 60 s apart, so frame_index n is minute n (the last frame is the end of the game).

Timelines are ~0.8 MB of JSON each, and DuckDB parses up to 2,048 rows per chunk, so parsing the whole
table at once runs out of memory. This model parses a range of match IDs at a time instead, with a
typed from_json schema so only the needed fields are materialized.
"""

import json

CHUNK = 200  # timelines parsed per batch
FIELDS = {
    "totalGold": "total_gold",
    "xp": "xp",
    "level": "level",
    "minionsKilled": "minions_killed",
    "jungleMinionsKilled": "jungle_minions_killed",
}


def id_ranges(session, relation: str):
    """Consecutive (first, last) match_id ranges of CHUNK timelines each. Parquet segments are
    written roughly in match_id order, so a range filter lets DuckDB skip most of the files."""
    ids = [r[0] for r in session.sql(f"select match_id from {relation} order by match_id").fetchall()]
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start : start + CHUNK]
        yield chunk[0], chunk[-1]


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
    for lo, hi in id_ranges(session, "_stg_timeline_frames_src"):
        session.sql(f"""
            insert into _stg_timeline_frames
            with parsed as (
                select match_id, from_json(payload -> '$.info.frames', '{schema}') as frames
                from _stg_timeline_frames_src
                where match_id between '{lo}' and '{hi}'
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
