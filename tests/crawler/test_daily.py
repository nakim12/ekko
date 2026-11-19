from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from crawler import daily, phase1
from crawler.config import Settings
from crawler.store import append_jsonl, read_records, stored_ids

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
AMERICAS = "https://americas.api.riotgames.com/lol/match/v5/matches"
NA1 = "https://na1.api.riotgames.com/lol/league/v4/entries/by-puuid"
OTHERS = [f"x{i}" for i in range(1, 10)]


def _settings(tmp_path) -> Settings:
    s = Settings(riot_api_key="RGAPI-test", rate_limits=((1000, 1.0),), data_dir=tmp_path)
    append_jsonl(phase1.control_dir(s) / "players.jsonl", {"puuid": "p1", "stratum": "GOLD"})
    return s


def _match(match_id: str, ended: datetime, queue: int = 420) -> dict:
    end_ms = int(ended.timestamp() * 1000)
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "queueId": queue,
            "gameStartTimestamp": end_ms - 30 * 60_000,
            "gameEndTimestamp": end_ms,
            "participants": [{"puuid": p} for p in ["p1", *OTHERS]],
        },
    }


def _mock_api(recent: dict[str, dict]):
    def ids(request, puuid):
        params = request.url.params
        if "startTime" in params:  # recent matches of a focal player
            return httpx.Response(200, json=sorted(recent))
        n = int(params["count"])  # history before a match
        return httpx.Response(200, json=[f"NA1_9{puuid}{k}" for k in range(n)])

    def match(request, match_id):
        payload = recent.get(match_id) or {"metadata": {"matchId": match_id}, "info": {}}
        return httpx.Response(200, json=payload)

    def league(request, puuid):
        if puuid == "x9":
            return httpx.Response(200, json=[])  # unranked in solo queue
        entry = {"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II", "leaguePoints": 40}
        return httpx.Response(200, json=[{"queueType": "RANKED_FLEX_SR"}, entry])

    respx.get(url__regex=rf"{AMERICAS}/by-puuid/(?P<puuid>\w+)/ids").mock(side_effect=ids)
    respx.get(url__regex=rf"{AMERICAS}/(?P<match_id>NA1_\w+)$").mock(side_effect=match)
    respx.get(url__regex=rf"{NA1}/(?P<puuid>\w+)$").mock(side_effect=league)


@respx.mock
async def test_q2_records_ranks_placebo_history_and_statuses(tmp_path):
    settings = _settings(tmp_path)
    recent = {
        "NA1_10": _match("NA1_10", NOW - timedelta(hours=1)),
        "NA1_11": _match("NA1_11", NOW - timedelta(hours=1), queue=400),
        "NA1_12": _match("NA1_12", NOW - timedelta(hours=25)),
    }
    _mock_api(recent)
    await daily.q2(
        settings, window_hours=8, max_matches=10, seed=1, autofill_rate=0.0, now=lambda: NOW
    )

    status = {r["match_id"]: r["status"] for r in read_records(settings.raw_dir, "q2_matches")}
    assert status == {"NA1_10": "qualified", "NA1_11": "not_ranked_solo", "NA1_12": "too_old"}

    ranks = [r for r in read_records(settings.raw_dir, "q2_ranks") if r["match_id"] == "NA1_10"]
    assert len(ranks) == 10
    assert {r["puuid"]: r["found"] for r in ranks}["x9"] is False
    assert {r["tier"] for r in ranks if r["found"]} == {"GOLD"}  # the solo entry, not flex

    history = read_records(settings.raw_dir, "q2_history")
    assert [(h["match_id"], h["purpose"], len(h["previous_match_ids"])) for h in history] == [
        ("NA1_10", "placebo", 5)
    ]
    registry = {r["match_id"]: r for r in read_records(settings.raw_dir, "q2_matches")}
    assert registry["NA1_10"]["focal_puuid"] == "p1"
    assert registry["NA1_10"]["placebo_puuid"] == history[0]["puuid"] != "p1"
    stored = stored_ids(settings.raw_dir, "matches")
    assert {"NA1_10", *history[0]["previous_match_ids"]} <= stored

    # A second run skips everything already registered.
    calls = respx.calls.call_count
    await daily.q2(
        settings, window_hours=8, max_matches=10, seed=1, autofill_rate=0.0, now=lambda: NOW
    )
    assert len(read_records(settings.raw_dir, "q2_matches")) == 3
    assert respx.calls.call_count == calls + 1  # just the recent-matches lookup


@respx.mock
async def test_q2_autofill_sample_fetches_every_other_player_s_history(tmp_path):
    settings = _settings(tmp_path)
    _mock_api({"NA1_10": _match("NA1_10", NOW - timedelta(hours=1))})
    await daily.q2(
        settings, window_hours=8, max_matches=10, seed=1, autofill_rate=1.0, now=lambda: NOW
    )
    history = read_records(settings.raw_dir, "q2_history")
    autofill = [h for h in history if h["purpose"] == "autofill"]
    assert sorted(h["puuid"] for h in autofill) == OTHERS
    assert all(len(h["previous_match_ids"]) == 20 for h in autofill)


@pytest.mark.parametrize("already_today", [False, True])
@respx.mock
async def test_snapshots_once_per_day(tmp_path, already_today):
    settings = _settings(tmp_path)
    _mock_api({})
    if already_today:
        await daily.snapshots(settings, now=lambda: NOW)
    await daily.snapshots(settings, now=lambda: NOW)
    rows = read_records(settings.raw_dir, "rank_snapshots")
    assert len(rows) == 1
    assert rows[0]["puuid"] == "p1" and rows[0]["tier"] == "GOLD" and rows[0]["league_points"] == 40
