import asyncio
import random
from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures.synthetic_warehouse import ROLES, Generator

PUUID = "me-0001"


class FakeRiot:
    """The RiotClient methods a lookup uses, backed by synthetic match-v5 payloads."""

    def __init__(self, n_games: int = 60, seed: int = 1, delay: float = 0.0) -> None:
        self.g = Generator(seed)
        self.delay = delay
        self.calls = 0
        rng = random.Random(seed)
        clock = datetime(2026, 11, 1, 18, tzinfo=UTC)
        self.ids = []
        for k in range(n_games):
            minutes = 2.5 if k == 3 else rng.uniform(20, 35)
            self.ids.append(
                self.g.match(
                    clock,
                    {PUUID: (100, ROLES[k % 5])},
                    minutes,
                    rng.random() < 0.5,
                    remake=(k == 3),
                )
            )
            clock += timedelta(
                minutes=minutes
                + (rng.uniform(2, 40) if rng.random() < 0.6 else rng.uniform(70, 900))
            )
        self.ids.reverse()  # match-v5 returns newest first

    async def _tick(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)

    async def account_by_riot_id(self, name, tag):
        await self._tick()
        return (
            {"puuid": PUUID, "gameName": name, "tagLine": tag} if name.lower() == "tester" else None
        )

    async def ranked_entry_by_puuid(self, puuid):
        await self._tick()
        return {"tier": "GOLD", "rank": "II", "leaguePoints": 40}

    async def ranked_match_ids(self, puuid, count=100, **_):
        await self._tick()
        return self.ids[:count]

    async def match(self, match_id):
        await self._tick()
        return self.g.matches.get(match_id)

    async def timeline(self, match_id):
        await self._tick()
        return self.g.timelines.get(match_id)


@pytest.fixture
def riot():
    return FakeRiot()
