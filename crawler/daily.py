"""Scheduled jobs: daily rank snapshots and the Q2 (loser's queue) collection.

    python -m crawler.daily snapshots   # once a day: each focal player's current solo rank
    python -m crawler.daily q2          # every 6 hours: recent matches + ranks of all 10 players

Q2 (PREREGISTRATION.md 4.4 and 7.1): for focal players' matches that ended recently, look up the
current solo rank of all 10 participants within 24 hours of the match ending, until 10,000 matches
qualify. Per match, the focal player's previous 5 ranked games are fetched (their streak state;
games after the main crawl aren't otherwise stored), as are a random non-focal participant's (the
placebo), and a random ~10% of matches also get every non-focal participant's previous 20 games
(H2a, likely-autofilled roles). Choices are seeded by match ID, so they're reproducible.

The rank-lookup rate limit (~50 per minute on the platform host) makes a run take hours, so q2
looks back `--window-hours` (default 8) and is meant to run every 6 hours; matches seen before are
skipped. A match whose lookups finish more than 24 hours after it ended is recorded as too_old.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pyarrow as pa

from crawler.config import RANKED_SOLO_QUEUE_ID, Settings, load_settings
from crawler.phase1 import control_dir, log
from crawler.riot import RiotAPIError, RiotClient, client_scope
from crawler.store import RecordWriter, SegmentWriter, read_jsonl, read_records, stored_ids

Q2_TARGET = 10_000
LOOKUP_DEADLINE = timedelta(hours=24)
STREAK_GAMES = 5  # enough to classify L3+ through W3+ even with a remake
AUTOFILL_GAMES = 20
AUTOFILL_RATE = 0.10

TS = pa.timestamp("us", tz="UTC")
RANK_FIELDS = [
    ("found", pa.bool_()),
    ("tier", pa.string()),
    ("rank", pa.string()),
    ("league_points", pa.int32()),
    ("wins", pa.int32()),
    ("losses", pa.int32()),
]
SNAPSHOT_SCHEMA = pa.schema([("puuid", pa.string()), ("snapshot_at", TS), *RANK_FIELDS])
Q2_RANK_SCHEMA = pa.schema(
    [("match_id", pa.string()), ("puuid", pa.string()), ("looked_up_at", TS), *RANK_FIELDS]
)
Q2_MATCH_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("status", pa.string()),  # qualified | too_old | not_ranked_solo | missing
        ("focal_puuid", pa.string()),
        ("placebo_puuid", pa.string()),
        ("autofill_sample", pa.bool_()),
        ("game_end_at", TS),
        ("ranks_looked_up_at", TS),
        ("processed_at", TS),
    ]
)
Q2_HISTORY_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("puuid", pa.string()),
        ("purpose", pa.string()),  # focal | placebo | autofill
        ("previous_match_ids", pa.list_(pa.string())),
    ]
)


def rank_fields(entry: dict | None) -> dict:
    if entry is None:
        return {
            "found": False,
            "tier": None,
            "rank": None,
            "league_points": None,
            "wins": None,
            "losses": None,
        }
    return {
        "found": True,
        "tier": entry.get("tier"),
        "rank": entry.get("rank"),
        "league_points": entry.get("leaguePoints"),
        "wins": entry.get("wins"),
        "losses": entry.get("losses"),
    }


def focal_players(settings: Settings) -> list[str]:
    return [p["puuid"] for p in read_jsonl(control_dir(settings) / "players.jsonl")]


# --- snapshots ---


async def snapshots(
    settings: Settings,
    concurrency: int = 10,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    client: RiotClient | None = None,
) -> None:
    today = now().date().isoformat()
    done = {
        r["puuid"]
        for r in read_records(settings.raw_dir, "rank_snapshots", ["puuid", "snapshot_at"])
        if r["snapshot_at"].date().isoformat() == today
    }
    todo = [p for p in focal_players(settings) if p not in done]
    log(f"snapshots: {len(todo)} players to snapshot today")
    writer = RecordWriter(settings.raw_dir, "rank_snapshots", SNAPSHOT_SCHEMA)
    semaphore = asyncio.Semaphore(concurrency)
    async with client_scope(settings, client) as client:

        async def one(puuid: str) -> None:
            async with semaphore:
                entry = await client.ranked_entry_by_puuid(puuid)
                writer.add({"puuid": puuid, "snapshot_at": now(), **rank_fields(entry)})

        try:
            await asyncio.gather(*(one(p) for p in todo))
        finally:
            writer.flush()
    log(f"snapshots: wrote {writer.written}")


# --- q2 ---


class Q2Collector:
    def __init__(
        self,
        settings: Settings,
        client: RiotClient,
        seed: int,
        autofill_rate: float,
        now: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.client = client
        self.seed = seed
        self.autofill_rate = autofill_rate
        self.now = now
        self.focal = set(focal_players(settings))
        raw = settings.raw_dir
        self.matches = SegmentWriter(raw, "matches")
        self.have_matches = stored_ids(raw, "matches")
        self.registry = RecordWriter(raw, "q2_matches", Q2_MATCH_SCHEMA, flush_every=50)
        self.ranks = RecordWriter(raw, "q2_ranks", Q2_RANK_SCHEMA)
        self.history = RecordWriter(raw, "q2_history", Q2_HISTORY_SCHEMA)

    def flush(self) -> None:
        for w in (self.matches, self.ranks, self.history, self.registry):
            w.flush()

    async def _ensure_stored(self, match_ids: list[str]) -> None:
        for match_id in match_ids:
            if match_id in self.have_matches:
                continue
            self.have_matches.add(match_id)
            payload = await self.client.match(match_id)
            if payload is not None:
                self.matches.add(match_id, payload)

    async def _history(self, match_id: str, puuid: str, before_ms: int, n: int, purpose: str):
        ids = await self.client.ranked_match_ids(puuid, count=n, end_time=before_ms // 1000 - 1)
        await self._ensure_stored(ids)
        self.history.add(
            {"match_id": match_id, "puuid": puuid, "purpose": purpose, "previous_match_ids": ids}
        )

    def _register(self, match_id: str, status: str, **fields) -> str:
        record = {
            "match_id": match_id,
            "status": status,
            "focal_puuid": None,
            "placebo_puuid": None,
            "autofill_sample": None,
            "game_end_at": None,
            "ranks_looked_up_at": None,
            "processed_at": self.now(),
            **fields,
        }
        self.registry.add(record)
        return status

    async def process(self, match_id: str) -> str:
        payload = await self.client.match(match_id)
        if payload is None:
            return self._register(match_id, "missing")
        if match_id not in self.have_matches:
            self.have_matches.add(match_id)
            self.matches.add(match_id, payload)
        info = payload["info"]
        if info.get("queueId") != RANKED_SOLO_QUEUE_ID:
            return self._register(match_id, "not_ranked_solo")

        game_end = datetime.fromtimestamp(info["gameEndTimestamp"] / 1000, UTC)
        puuids = sorted(p["puuid"] for p in info["participants"])
        rng = random.Random(f"{self.seed}:{match_id}")
        focal = rng.choice(sorted(set(puuids) & self.focal))
        others = [p for p in puuids if p != focal]
        placebo = rng.choice(others)
        autofill = rng.random() < self.autofill_rate

        entries = await asyncio.gather(*(self.client.ranked_entry_by_puuid(p) for p in puuids))
        looked_up_at = self.now()
        for puuid, entry in zip(puuids, entries, strict=True):
            self.ranks.add(
                {
                    "match_id": match_id,
                    "puuid": puuid,
                    "looked_up_at": looked_up_at,
                    **rank_fields(entry),
                }
            )
        fields = {
            "focal_puuid": focal,
            "placebo_puuid": placebo,
            "autofill_sample": autofill,
            "game_end_at": game_end,
            "ranks_looked_up_at": looked_up_at,
        }
        if looked_up_at - game_end > LOOKUP_DEADLINE:
            return self._register(match_id, "too_old", **fields)

        start_ms = info["gameStartTimestamp"]
        await self._history(match_id, focal, start_ms, STREAK_GAMES, "focal")
        await self._history(match_id, placebo, start_ms, STREAK_GAMES, "placebo")
        if autofill:
            for puuid in others:
                await self._history(match_id, puuid, start_ms, AUTOFILL_GAMES, "autofill")
        return self._register(match_id, "qualified", **fields)


async def q2(
    settings: Settings,
    window_hours: float,
    max_matches: int,
    seed: int,
    autofill_rate: float = AUTOFILL_RATE,
    target: int = Q2_TARGET,
    concurrency: int = 5,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    client: RiotClient | None = None,
) -> None:
    registry = read_records(settings.raw_dir, "q2_matches", ["match_id", "status"])
    seen = {r["match_id"] for r in registry}
    qualified = sum(r["status"] == "qualified" for r in registry)
    if qualified >= target:
        log(f"q2: target reached ({qualified} qualified matches)")
        return

    async with client_scope(settings, client) as client:
        collector = Q2Collector(settings, client, seed, autofill_rate, now)
        since = int((now() - timedelta(hours=window_hours)).timestamp())
        candidates: set[str] = set()
        for puuid in sorted(collector.focal):
            candidates.update(await client.ranked_match_ids(puuid, count=20, start_time=since))
        todo = sorted(candidates - seen)
        random.Random(f"{seed}:{now().isoformat()}").shuffle(todo)
        todo = todo[: min(max_matches, target - qualified)]
        log(
            f"q2: {len(candidates)} recent matches, {len(todo)} new to process "
            f"({qualified} qualified so far)"
        )

        semaphore = asyncio.Semaphore(concurrency)
        counts: dict[str, int] = {}

        async def one(match_id: str) -> None:
            async with semaphore:
                status = await collector.process(match_id)
                counts[status] = counts.get(status, 0) + 1
                if sum(counts.values()) % 50 == 0:
                    log(f"q2: {counts}")

        try:
            await asyncio.gather(*(one(m) for m in todo))
        finally:
            collector.flush()
        log(f"q2: done {counts}, {client.request_count} requests")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshots")
    q = sub.add_parser("q2")
    q.add_argument("--window-hours", type=float, default=8.0)
    q.add_argument("--max-matches", type=int, default=400)
    q.add_argument("--seed", type=int, default=20261119)
    q.add_argument("--autofill-rate", type=float, default=AUTOFILL_RATE)
    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        if args.command == "snapshots":
            asyncio.run(snapshots(settings))
        else:
            asyncio.run(
                q2(settings, args.window_hours, args.max_matches, args.seed, args.autofill_rate)
            )
    except RiotAPIError as e:
        log(f"stopped: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
