import httpx
import respx

from crawler import phase1
from crawler.config import Settings
from crawler.store import SegmentWriter, append_jsonl, read_jsonl, stored_ids

BASE = "https://americas.api.riotgames.com/lol/match/v5/matches"


def _settings(tmp_path) -> Settings:
    return Settings(riot_api_key="RGAPI-test", rate_limits=((1000, 1.0),), data_dir=tmp_path)


def _setup(tmp_path, ids):
    settings = _settings(tmp_path)
    append_jsonl(phase1.control_dir(settings) / "match_ids.jsonl", {"puuid": "p1", "ids": ids})
    return settings


def _mock(status_for=lambda match_id, kind: 200):
    def handler(request, match_id, rest):
        kind = "timelines" if rest else "matches"
        status = status_for(match_id, kind)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"metadata": {"matchId": match_id}, "kind": kind})

    return respx.get(url__regex=rf"{BASE}/(?P<match_id>NA1_\d+)(?P<rest>/timeline)?$").mock(
        side_effect=handler
    )


@respx.mock
async def test_fetch_stores_both_kinds_skips_existing_and_records_404s(tmp_path):
    settings = _setup(tmp_path, ["NA1_1", "NA1_2", "NA1_3"])
    pre = SegmentWriter(settings.raw_dir, "matches")
    pre.add("NA1_1", {"already": True})
    pre.flush()
    route = _mock(lambda m, kind: 404 if (m, kind) == ("NA1_3", "timelines") else 200)

    assert await phase1.fetch(settings, concurrency=3, max_docs=None) == 0
    assert route.call_count == 5  # 6 documents minus the stored match
    assert stored_ids(settings.raw_dir, "matches") == {"NA1_1", "NA1_2", "NA1_3"}
    assert stored_ids(settings.raw_dir, "timelines") == {"NA1_1", "NA1_2"}
    missing = list(read_jsonl(phase1.control_dir(settings) / "missing.jsonl"))
    assert missing == [{"kind": "timelines", "match_id": "NA1_3"}]

    assert await phase1.fetch(settings, concurrency=3, max_docs=None) == 0
    assert route.call_count == 5  # nothing left to do, and the 404 isn't retried


@respx.mock
async def test_fetch_stops_on_expired_key_and_keeps_what_it_fetched(tmp_path):
    settings = _setup(tmp_path, [f"NA1_{i}" for i in range(1, 7)])
    _mock(lambda m, kind: 401 if m == "NA1_4" else 200)

    assert await phase1.fetch(settings, concurrency=1, max_docs=None) == 2
    assert stored_ids(settings.raw_dir, "matches") == {"NA1_1", "NA1_2", "NA1_3"}
    assert stored_ids(settings.raw_dir, "timelines") == {"NA1_1", "NA1_2", "NA1_3"}


@respx.mock
async def test_fetch_respects_max_docs(tmp_path):
    settings = _setup(tmp_path, ["NA1_1", "NA1_2", "NA1_3"])
    route = _mock()
    await phase1.fetch(settings, concurrency=2, max_docs=2)
    assert route.call_count == 2
    assert stored_ids(settings.raw_dir, "matches") == {"NA1_1"}
    assert stored_ids(settings.raw_dir, "timelines") == {"NA1_1"}
