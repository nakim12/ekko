from datetime import UTC, datetime

from crawler.store import SegmentWriter, append_jsonl, read_jsonl, stored_ids


def test_segments_flush_at_threshold_and_are_the_checkpoint(tmp_path):
    w = SegmentWriter(
        tmp_path, "matches", flush_every=2, clock=lambda: datetime(2026, 11, 19, tzinfo=UTC)
    )
    w.add("NA1_1", {"a": 1})
    assert stored_ids(tmp_path, "matches") == set()  # still buffered
    w.add("NA1_2", {"a": 2})  # threshold reached: one segment written
    w.add("NA1_3", {"a": 3})
    assert stored_ids(tmp_path, "matches") == {"NA1_1", "NA1_2"}
    w.flush()
    assert stored_ids(tmp_path, "matches") == {"NA1_1", "NA1_2", "NA1_3"}
    assert w.written == 3
    assert all(p.parent.name == "dt=2026-11-19" for p in (tmp_path / "matches").rglob("*.parquet"))
    assert not list((tmp_path / "matches").rglob("*.tmp"))


def test_read_jsonl_skips_a_torn_last_line(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"n": 1})
    with path.open("a") as f:
        f.write('{"n": 2')  # killed mid-write
    assert list(read_jsonl(path)) == [{"n": 1}]
    assert list(read_jsonl(tmp_path / "absent.jsonl")) == []
