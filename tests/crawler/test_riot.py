import httpx
import pytest
import respx

from crawler.config import Settings
from crawler.riot import RateLimiter, RiotAPIError, RiotClient


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_rate_limiter_waits_for_the_tightest_window(monkeypatch):
    clock = FakeClock()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    monkeypatch.setattr("crawler.riot.asyncio.sleep", fake_sleep)
    limiter = RateLimiter(((2, 1.0), (3, 10.0)), clock=clock)

    for _ in range(3):
        await limiter.acquire()
    # Two requests at t=0 fill the 1s window, so the third waits until t=1.
    assert slept == [1.0]

    await limiter.acquire()
    # Three requests within 10s: the fourth waits until the first expires at t=10.
    assert clock.now == pytest.approx(10.0)


def _client() -> RiotClient:
    settings = Settings(riot_api_key="RGAPI-test", rate_limits=((100, 1.0),))
    return RiotClient(settings, http=httpx.AsyncClient())


@respx.mock
async def test_retries_after_429_and_5xx(monkeypatch):
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("crawler.riot.asyncio.sleep", no_sleep)
    route = respx.get("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_1").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(503),
            httpx.Response(200, json={"metadata": {"matchId": "NA1_1"}}),
        ]
    )
    async with _client() as client:
        assert await client.match("NA1_1") == {"metadata": {"matchId": "NA1_1"}}
    assert route.call_count == 3


@respx.mock
async def test_404_returns_none_and_401_raises():
    respx.get("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_404").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_401").mock(
        return_value=httpx.Response(401)
    )
    async with _client() as client:
        assert await client.match("NA1_404") is None
        with pytest.raises(RiotAPIError, match="invalid or expired"):
            await client.match("NA1_401")
