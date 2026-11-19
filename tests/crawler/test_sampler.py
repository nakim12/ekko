import pytest

from crawler.sampler import APEX, Sampler, SampleState, page_count
from crawler.store import read_jsonl


class FakeLadder:
    """league-v4 and match-v5 stand-ins. Entries are generated per (tier, division, page)."""

    def __init__(self, pages: dict[str, int], page_size: int = 10) -> None:
        self.pages = pages  # division -> number of pages
        self.page_size = page_size
        self.calls = 0

    def _entry(self, tier, division, page, i):
        puuid = f"{tier}-{division}-{page}-{i}"
        return {
            "puuid": puuid,
            "inactive": i % 7 == 0,
            "leaguePoints": i,
            "wins": 10,
            "losses": 10,
            "rank": division,
        }

    async def league_entries(self, tier, division, page=1):
        self.calls += 1
        if page > self.pages.get(division, 0):
            return []
        return [self._entry(tier, division, page, i) for i in range(self.page_size)]

    async def apex_league(self, tier):
        return [self._entry(tier, "I", 1, i) for i in range(5)]

    async def ranked_match_ids(self, puuid, start=0, count=100, **_):
        n = 20 if puuid.endswith("-3") else 100  # entry 3 of each page has too few games
        return [f"NA1_{puuid}_{k}" for k in range(start, min(n, start + count))]


@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 17, 64])
async def test_page_count(n):
    ladder = FakeLadder({"I": n})
    assert await page_count(ladder, "GOLD", "I") == n
    assert ladder.calls <= 2 * max(n, 1).bit_length() + 2


def _sampler(tmp_path, ladder, seed=1, excluded=frozenset()):
    return Sampler(ladder, SampleState.load(tmp_path), set(excluded), seed)


async def test_ladder_sample_keeps_only_eligible_players(tmp_path):
    ladder = FakeLadder({"I": 3, "II": 1, "III": 0, "IV": 6})
    excluded = {"GOLD-IV-1-1", "GOLD-IV-2-2"}
    s = _sampler(tmp_path, ladder, excluded=excluded)
    await s.sample_ladder_tier("GOLD", 12)

    players = list(read_jsonl(tmp_path / "players.jsonl"))
    assert len(players) == 12
    puuids = [p["puuid"] for p in players]
    assert len(set(puuids)) == 12
    assert not set(puuids) & excluded
    for p in players:
        _, division, page, i = p["puuid"].split("-")
        assert int(i) % 7 != 0 and i != "3"  # not inactive, enough games
        assert division != "III"  # empty division never drawn
    log = list(read_jsonl(tmp_path / "sample_log.jsonl"))
    assert {d["outcome"] for d in log} >= {"accepted"}
    assert [d["draw"] for d in log] == list(range(len(log)))
    first = {r["puuid"]: r["ids"] for r in read_jsonl(tmp_path / "first_match_ids.jsonl")}
    assert set(first) == set(puuids) and all(len(v) == 100 for v in first.values())


async def test_resumed_sample_matches_an_uninterrupted_one(tmp_path):
    pages = {"I": 4, "II": 4, "III": 4, "IV": 4}
    await _sampler(tmp_path / "once", FakeLadder(pages), seed=7).sample_ladder_tier("SILVER", 10)

    await _sampler(tmp_path / "twice", FakeLadder(pages), seed=7).sample_ladder_tier("SILVER", 4)
    await _sampler(tmp_path / "twice", FakeLadder(pages), seed=7).sample_ladder_tier("SILVER", 10)

    def puuids(d):
        return [p["puuid"] for p in read_jsonl(d / "players.jsonl")]

    assert puuids(tmp_path / "once") == puuids(tmp_path / "twice")


async def test_apex_draws_from_all_three_lists(tmp_path):
    s = _sampler(tmp_path, FakeLadder({}), seed=3)
    await s.sample_apex(6)
    players = list(read_jsonl(tmp_path / "players.jsonl"))
    assert len(players) == 6
    assert all(p["stratum"] == APEX for p in players)
    assert {p["tier"] for p in players} <= {"MASTER", "GRANDMASTER", "CHALLENGER"}
