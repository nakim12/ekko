import asyncio

from crawler import supervisor
from crawler.config import Settings
from crawler.riot import RiotAPIError
from crawler.store import append_jsonl


def _settings(tmp_path) -> Settings:
    return Settings(riot_api_key="RGAPI-test", data_dir=tmp_path)


async def test_scheduled_jobs_wait_for_the_sample_then_share_the_client(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls = []
    clients = set()

    async def crawl(s, client):
        clients.add(id(client))
        await asyncio.sleep(0)
        append_jsonl(supervisor.control_dir(s) / "players.jsonl", {"puuid": "p1"})
        calls.append("crawl")

    async def snapshots(s, client):
        clients.add(id(client))
        calls.append("snapshots")

    async def q2(s, *args, client):
        clients.add(id(client))
        calls.append("q2")
        raise RiotAPIError("401 from Riot: API key invalid or expired")  # end the run

    monkeypatch.setattr(supervisor, "crawl", crawl)
    monkeypatch.setattr(supervisor.daily, "snapshots", snapshots)
    monkeypatch.setattr(supervisor.daily, "q2", q2)
    monkeypatch.setattr(supervisor, "POLL_SECONDS", 0)

    assert await supervisor.supervise(settings) == 2
    assert calls[0] == "crawl" and calls[1:] == ["snapshots", "q2"]
    assert len(clients) == 1


async def test_expired_key_in_the_crawl_stops_everything(tmp_path, monkeypatch):
    async def crawl(s, client):
        raise RiotAPIError("401 from Riot: API key invalid or expired")

    async def never(s, client):
        await asyncio.sleep(3600)

    monkeypatch.setattr(supervisor, "crawl", crawl)
    monkeypatch.setattr(supervisor, "scheduled", never)
    assert await asyncio.wait_for(supervisor.supervise(_settings(tmp_path)), 5) == 2
