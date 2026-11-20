"""Expose the raw landing zone to the warehouse as views in the `raw` schema.

    python -m crawler.load

Views read the Parquet segments in place (absolute paths), so new segments show up without
reloading. The dbt sources read these names. Build on the Phase 1 sample (instead of Phase 0), with
the Q2 models enabled, using --vars '{phase: 1}'.

Documents are never stored twice (every writer checks what's stored first), so the views don't
deduplicate; dbt's unique tests on match_id catch it if that ever breaks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pyarrow as pa

from crawler.config import Settings, load_settings
from crawler.phase1 import control_dir, log

DOCUMENT_KINDS = ("matches", "timelines")
RECORD_TABLES = ("rank_snapshots", "q2_matches", "q2_ranks", "q2_history")


def _parquet_glob(raw_dir: Path, name: str) -> str | None:
    root = (raw_dir / name).resolve()
    return f"{root}/dt=*/*.parquet" if any(root.glob("dt=*/*.parquet")) else None


def _replace_view(con: duckdb.DuckDBPyConnection, name: str, select: str) -> None:
    """(Re)create raw.<name> as a view, replacing a table of that name (Phase 0 loaded tables)."""
    is_table = con.execute(
        "select count(*) from information_schema.tables "
        "where table_schema = 'raw' and table_name = ? and table_type = 'BASE TABLE'",
        [name],
    ).fetchall()[0][0]
    if is_table:
        con.execute(f"drop table raw.{name}")
    con.execute(f"create or replace view raw.{name} as {select}")


def _phase0_player_match_ids(settings: Settings) -> pa.Table | None:
    files = sorted((settings.raw_dir / "phase0" / "match_ids").glob("*.json"))
    pairs = [(f.stem, m) for f in files for m in json.loads(f.read_text())]
    if not pairs:
        return None
    puuids, match_ids = zip(*pairs, strict=True)
    return pa.table({"puuid": list(puuids), "match_id": list(match_ids)})


def load(settings: Settings) -> dict[str, int]:
    counts: dict[str, int] = {}
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute("create schema if not exists raw")
        for kind in DOCUMENT_KINDS:
            if glob := _parquet_glob(settings.raw_dir, kind):
                _replace_view(
                    con,
                    kind,
                    "select match_id, payload::json as payload "
                    f"from read_parquet('{glob}', union_by_name = true)",
                )
        for name in RECORD_TABLES:
            if glob := _parquet_glob(settings.raw_dir, name):
                _replace_view(con, name, f"select * from read_parquet('{glob}')")

        control = control_dir(settings).resolve()
        if (control / "players.jsonl").exists():
            _replace_view(
                con, "players", f"select * from read_json_auto('{control}/players.jsonl')"
            )
        # Each focal player's crawled match IDs: the games that make up their history. Q2 and
        # placebo matches share the document store but aren't part of it.
        if (control / "match_ids.jsonl").exists():
            _replace_view(
                con,
                "player_match_ids",
                "select puuid, unnest(ids) as match_id "
                f"from read_json_auto('{control}/match_ids.jsonl')",
            )
        if (phase0 := _phase0_player_match_ids(settings)) is not None:
            con.register("phase0_ids", phase0)
            con.execute(
                "create or replace table raw.phase0_player_match_ids as select * from phase0_ids"
            )
            con.unregister("phase0_ids")

        for (name,) in con.execute(
            "select table_name from information_schema.tables where table_schema = 'raw' order by 1"
        ).fetchall():
            counts[name] = con.execute(f"select count(*) from raw.{name}").fetchall()[0][0]
    return counts


def main() -> int:
    for name, n in load(load_settings(require_key=False)).items():
        log(f"raw.{name}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
