"""Async Riot API client with a per-host sliding-window rate limiter.

Riot enforces app rate limits per routing value (na1, americas, ...), so each host gets its own
limiter. 429s honour Retry-After; 5xx and network errors back off and retry; 404 returns None.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from crawler.config import RANKED_SOLO_QUEUE_ID, RANKED_SOLO_QUEUE_NAME, Settings

MAX_ATTEMPTS = 6


class RiotAPIError(RuntimeError):
    pass


class RateLimiter:
    """Sliding-window limiter enforcing several (requests, window seconds) limits at once."""

    def __init__(
        self,
        limits: tuple[tuple[int, float], ...],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._history: deque[float] = deque()
        self._longest_window = max(window for _, window in limits)
        self._lock = asyncio.Lock()

    def _wait_time(self, now: float) -> float:
        while self._history and now - self._history[0] >= self._longest_window:
            self._history.popleft()
        wait = 0.0
        for requests, window in self._limits:
            in_window = [t for t in self._history if now - t < window]
            if len(in_window) >= requests:
                # The oldest request that must expire before one more fits.
                wait = max(wait, in_window[-requests] + window - now)
        return wait

    async def acquire(self) -> None:
        async with self._lock:
            while (wait := self._wait_time(self._clock())) > 0:
                await asyncio.sleep(wait)
            self._history.append(self._clock())


class RiotClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(
            timeout=30.0, headers={"X-Riot-Token": settings.riot_api_key}
        )
        self._limiters: dict[str, RateLimiter] = {}
        self.request_count = 0

    async def __aenter__(self) -> RiotClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    def _limiter(self, url: str) -> RateLimiter:
        host = httpx.URL(url).host
        if host not in self._limiters:
            self._limiters[host] = RateLimiter(self._settings.rate_limits)
        return self._limiters[host]

    async def get(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        limiter = self._limiter(url)
        for attempt in range(MAX_ATTEMPTS):
            await limiter.acquire()
            self.request_count += 1
            try:
                response = await self._http.get(url, params=params)
            except httpx.TransportError:
                await asyncio.sleep(min(2**attempt, 30))
                continue

            status = response.status_code
            if status == 200:
                return response.json()
            if status == 404:
                return None
            if status == 429:
                await asyncio.sleep(float(response.headers.get("Retry-After", "10")))
                continue
            if status >= 500:
                await asyncio.sleep(min(2**attempt, 30))
                continue
            if status in (401, 403):
                raise RiotAPIError(f"{status} from Riot: API key invalid or expired")
            raise RiotAPIError(f"{status} from Riot for {url}: {response.text[:200]}")
        raise RiotAPIError(f"gave up after {MAX_ATTEMPTS} attempts: {url}")

    # --- platform routing (na1) ---

    async def league_entries(self, tier: str, division: str, page: int = 1) -> list[dict]:
        url = (
            f"{self._settings.platform_base_url}/lol/league/v4/entries/"
            f"{RANKED_SOLO_QUEUE_NAME}/{tier}/{division}"
        )
        return await self.get(url, params={"page": page}) or []

    async def ranked_entry_by_puuid(self, puuid: str) -> dict | None:
        """The player's current RANKED_SOLO_5x5 entry, or None if unranked in solo queue."""
        url = f"{self._settings.platform_base_url}/lol/league/v4/entries/by-puuid/{puuid}"
        entries = await self.get(url) or []
        return next((e for e in entries if e.get("queueType") == RANKED_SOLO_QUEUE_NAME), None)

    async def apex_league(self, tier: str) -> list[dict]:
        path = {
            "CHALLENGER": "challengerleagues",
            "GRANDMASTER": "grandmasterleagues",
            "MASTER": "masterleagues",
        }[tier]
        url = (
            f"{self._settings.platform_base_url}/lol/league/v4/{path}/by-queue/"
            f"{RANKED_SOLO_QUEUE_NAME}"
        )
        league = await self.get(url)
        return league["entries"] if league else []

    # --- regional routing (americas) ---

    async def ranked_match_ids(
        self,
        puuid: str,
        start: int = 0,
        count: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        """Ranked solo match IDs, newest first. start_time/end_time are epoch seconds."""
        url = f"{self._settings.regional_base_url}/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params: dict[str, int] = {"queue": RANKED_SOLO_QUEUE_ID, "start": start, "count": count}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return await self.get(url, params=params) or []

    async def match(self, match_id: str) -> dict | None:
        return await self.get(f"{self._settings.regional_base_url}/lol/match/v5/matches/{match_id}")

    async def timeline(self, match_id: str) -> dict | None:
        url = f"{self._settings.regional_base_url}/lol/match/v5/matches/{match_id}/timeline"
        return await self.get(url)
