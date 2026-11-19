"""Expose the raw landing zone to the warehouse as views in the `raw` schema.

    python -m crawler.load

Views read the Parquet segments in place (absolute paths), so new segments show up without
reloading. The dbt sources read these names; set the dbt var players_table=players to build on the
Phase 1 sample instead of Phase 0.

Documents are never stored twice (every writer checks what's stored first), so the views don't
deduplicate; dbt's unique tests on match_id catch it if that ever breaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from crawler.config import Settings, load_settings
from crawler.phase1 import control_dir, log

DOCUMENT_KINDS = ("matches", "timelines")
RECORD_TABLES = ("rank_snapshots", "q2_matches", "q2_ranks", "q2_history")


def _parquet_glob(raw_dir: Path, name: str) -> str | None:
    root = (raw_dir / name).resolve()
    return f"{root}/dt=*/*.parquet" if any(root.glob("dt=*/*.parquet")) else None


def load(settings: Settings) -> dict[str, int]:
    counts: dict[str, int] = {}
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute("create schema if not exists raw")
        for kind in DOCUMENT_KINDS:
            if glob := _parquet_glob(settings.raw_dir, kind):
                con.execute(f"drop table if exists raw.{kind}")
                con.execute(
                    f"create or replace view raw.{kind} as "
                    f"select match_id, payload::json as payload "
                    f"from read_parquet('{glob}', union_by_name = true)"
                )
        for name in RECORD_TABLES:
            if glob := _parquet_glob(settings.raw_dir, name):
                con.execute(
                    f"create or replace view raw.{name} as select * from read_parquet('{glob}')"
                )
        players = (control_dir(settings) / "players.jsonl").resolve()
        if players.exists():
            con.execute(
                f"create or replace view raw.players as select * from read_json_auto('{players}')"
            )
        for (name,) in con.execute(
            "select table_name from information_schema.tables where table_schema = 'raw' order by 1"
        ).fetchall():
            counts[name] = con.execute(f"select count(*) from raw.{name}").fetchall()[0][0]
    return counts


def main() -> int:
    for name, n in load(load_settings()).items():
        log(f"raw.{name}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
