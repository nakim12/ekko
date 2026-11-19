import duckdb
import pyarrow as pa

from crawler import phase1
from crawler.config import Settings
from crawler.load import load
from crawler.store import RecordWriter, SegmentWriter, append_jsonl


def test_load_exposes_landing_zone_as_raw_views(tmp_path):
    s = Settings(riot_api_key="x", data_dir=tmp_path, duckdb_path=tmp_path / "w.duckdb")
    for kind in ("matches", "timelines"):
        w = SegmentWriter(s.raw_dir, kind)
        w.add("NA1_1", {"info": {"queueId": 420}})
        w.flush()
    snaps = RecordWriter(s.raw_dir, "rank_snapshots", pa.schema([("puuid", pa.string())]))
    snaps.add({"puuid": "p1"})
    snaps.flush()
    append_jsonl(phase1.control_dir(s) / "players.jsonl", {"puuid": "p1", "tier": "GOLD"})

    counts = load(s)
    assert counts == {"matches": 1, "players": 1, "rank_snapshots": 1, "timelines": 1}
    with duckdb.connect(str(s.duckdb_path), read_only=True) as con:
        q = "select payload ->> '$.info.queueId' from raw.matches"
        assert con.execute(q).fetchall() == [("420",)]

    # New segments show up without reloading.
    w = SegmentWriter(s.raw_dir, "matches")
    w.add("NA1_2", {"info": {}})
    w.flush()
    with duckdb.connect(str(s.duckdb_path), read_only=True) as con:
        assert con.execute("select count(*) from raw.matches").fetchall() == [(2,)]
