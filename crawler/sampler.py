"""Stratified random sample of focal players (PREREGISTRATION.md section 3).

- Iron through Diamond: `per_tier` players each. A draw picks a division with probability
  proportional to its number of league-v4 pages, then a uniform page, then a uniform entry on that
  page, which approximates a uniform draw from everyone in the tier.
- Master, Grandmaster and Challenger: `apex` players drawn uniformly from the three lists combined.
- A drawn player is kept only if they are active, weren't in the Phase 0 sample, haven't already
  been drawn, and have at least `min_games` ranked solo games. Otherwise the draw is logged with the
  reason and another is made.

Every draw (kept or not) is appended to sample_log.jsonl. Draw n of a tier uses
random.Random(f"{seed}:{tier}:{n}"), so a resumed run continues the same sequence of draws.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crawler.config import APEX_TIERS, DIVISIONS
from crawler.riot import RiotClient
from crawler.store import append_jsonl, read_jsonl

LADDER_TIERS = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND")
APEX = "APEX"  # stratum label for Master+ combined
MIN_GAMES = 30
MAX_DRAWS_PER_STRATUM = 20_000  # a safety stop; logged if reached


@dataclass
class SampleState:
    """Control files for the sample, under data/raw/phase1/."""

    root: Path
    players: list[dict] = field(default_factory=list)
    draws_by_stratum: dict[str, int] = field(default_factory=dict)

    @property
    def players_path(self) -> Path:
        return self.root / "players.jsonl"

    @property
    def log_path(self) -> Path:
        return self.root / "sample_log.jsonl"

    @property
    def first_ids_path(self) -> Path:
        return self.root / "first_match_ids.jsonl"

    @classmethod
    def load(cls, root: Path) -> SampleState:
        state = cls(root)
        state.players = list(read_jsonl(state.players_path))
        for draw in read_jsonl(state.log_path):
            s = draw["stratum"]
            state.draws_by_stratum[s] = state.draws_by_stratum.get(s, 0) + 1
        return state

    def accepted(self, stratum: str) -> int:
        return sum(1 for p in self.players if p["stratum"] == stratum)

    def puuids(self) -> set[str]:
        return {p["puuid"] for p in self.players}


def draw_rng(seed: int, stratum: str, n: int) -> random.Random:
    return random.Random(f"{seed}:{stratum}:{n}")


async def page_count(client: RiotClient, tier: str, division: str) -> int:
    """Number of non-empty league-v4 pages: probe 1, 2, 4, ... then binary search."""
    if not await client.league_entries(tier, division, 1):
        return 0
    lo, hi = 1, 2
    while await client.league_entries(tier, division, hi):
        lo, hi = hi, hi * 2
    while hi - lo > 1:  # lo is non-empty, hi is empty
        mid = (lo + hi) // 2
        if await client.league_entries(tier, division, mid):
            lo = mid
        else:
            hi = mid
    return lo


class Sampler:
    def __init__(
        self,
        client: RiotClient,
        state: SampleState,
        excluded_puuids: set[str],
        seed: int,
        min_games: int = MIN_GAMES,
    ) -> None:
        self.client = client
        self.state = state
        self.excluded = excluded_puuids
        self.seed = seed
        self.min_games = min_games
        self._pages: dict[tuple[str, str, int], list[dict]] = {}
        self._lock = asyncio.Lock()  # control-file writes and the duplicate check

    async def _page(self, tier: str, division: str, page: int) -> list[dict]:
        key = (tier, division, page)
        if key not in self._pages:
            self._pages[key] = await self.client.league_entries(tier, division, page)
        return self._pages[key]

    async def _judge(self, entry: dict) -> tuple[str, list[str]]:
        """'accepted' or the rejection reason, plus the first page of match IDs if fetched."""
        puuid = entry.get("puuid")
        if not puuid:
            return "no_puuid", []
        if entry.get("inactive"):
            return "inactive", []
        if puuid in self.excluded:
            return "phase0_player", []
        if puuid in self.state.puuids():
            return "already_sampled", []
        ids = await self.client.ranked_match_ids(puuid, count=100)
        if len(ids) < self.min_games:
            return f"fewer_than_{self.min_games}_games", ids
        return "accepted", ids

    async def _record(self, stratum: str, tier: str, division: str, page: int | None, entry: dict):
        async with self._lock:
            n = self.state.draws_by_stratum.get(stratum, 0)
            outcome, ids = await self._judge(entry)
            now = datetime.now(UTC).isoformat()
            append_jsonl(
                self.state.log_path,
                {
                    "stratum": stratum,
                    "draw": n,
                    "tier": tier,
                    "division": division,
                    "page": page,
                    "puuid": entry.get("puuid"),
                    "outcome": outcome,
                    "at": now,
                },
            )
            self.state.draws_by_stratum[stratum] = n + 1
            if outcome != "accepted":
                return
            player = {
                "puuid": entry["puuid"],
                "stratum": stratum,
                "tier": tier,
                "division": division,
                "league_points": entry.get("leaguePoints"),
                "wins": entry.get("wins"),
                "losses": entry.get("losses"),
                "draw": n,
                "sampled_at": now,
            }
            append_jsonl(self.state.first_ids_path, {"puuid": entry["puuid"], "ids": ids})
            append_jsonl(self.state.players_path, player)
            self.state.players.append(player)

    async def sample_ladder_tier(self, tier: str, target: int) -> None:
        counts = {d: await page_count(self.client, tier, d) for d in DIVISIONS}
        divisions = [d for d in DIVISIONS if counts[d] > 0]
        if not divisions:
            return
        while self.state.accepted(tier) < target:
            n = self.state.draws_by_stratum.get(tier, 0)
            if n >= MAX_DRAWS_PER_STRATUM:
                print(f"{tier}: stopped after {n} draws", flush=True)
                return
            rng = draw_rng(self.seed, tier, n)
            division = rng.choices(divisions, weights=[counts[d] for d in divisions])[0]
            page = rng.randint(1, counts[division])
            entries = await self._page(tier, division, page)
            if not entries:  # the ladder shrank since counting; count the draw and move on
                await self._record(tier, tier, division, page, {})
                continue
            await self._record(tier, tier, division, page, rng.choice(entries))

    async def sample_apex(self, target: int) -> None:
        pool = []
        for tier in APEX_TIERS:
            pool += [(tier, e) for e in await self.client.apex_league(tier)]
        pool.sort(key=lambda te: (te[0], te[1].get("puuid") or ""))  # stable order for draws
        if not pool:
            return
        while self.state.accepted(APEX) < target:
            n = self.state.draws_by_stratum.get(APEX, 0)
            if n >= min(MAX_DRAWS_PER_STRATUM, 5 * len(pool)):
                print(f"{APEX}: stopped after {n} draws (pool {len(pool)})", flush=True)
                return
            tier, entry = draw_rng(self.seed, APEX, n).choice(pool)
            await self._record(APEX, tier, entry.get("rank", "I"), None, entry)

    async def run(self, per_tier: int, apex: int) -> None:
        jobs = [self.sample_ladder_tier(t, per_tier) for t in LADDER_TIERS]
        await asyncio.gather(*jobs, self.sample_apex(apex))
