"""One long-running process for the Fly.io machine: the Phase 1 crawl plus the scheduled jobs.

    python -m crawler.supervisor

A Fly volume attaches to one machine, and Riot's rate limits are per key, so everything runs here
on one shared client:
- the crawl (sample, match IDs, matches and timelines), once, resuming whatever is unfinished;
- rank snapshots once per UTC day;
- the Q2 collection every 6 hours, looking back 8 hours, until its target is reached.

The scheduled jobs start once the sample exists. If the key expires (401/403), everything stops
and the process exits cleanly, so the machine doesn't restart-loop on a dead key; set a new key
with `fly secrets set`, which restarts it. Every job resumes from what's on disk.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from crawler import daily, phase1
from crawler.config import Settings, load_settings
from crawler.phase1 import control_dir, log
from crawler.riot import RiotAPIError, RiotClient
from crawler.store import read_jsonl

Q2_EVERY = timedelta(hours=6)
Q2_WINDOW_HOURS = 8.0
Q2_MAX_MATCHES = 400
POLL_SECONDS = 300
SEED = 20261119


def sample_exists(settings: Settings) -> bool:
    return any(True for _ in read_jsonl(control_dir(settings) / "players.jsonl"))


async def crawl(settings: Settings, client: RiotClient) -> None:
    await phase1.sample(settings, per_tier=250, apex=250, seed=SEED, client=client)
    await phase1.match_ids(settings, games=phase1.GAMES_PER_PLAYER, client=client)
    if await phase1.fetch(settings, concurrency=10, max_docs=None, client=client) == 2:
        raise RiotAPIError("401/403 from Riot: API key invalid or expired")
    log("crawl: complete")


async def scheduled(settings: Settings, client: RiotClient) -> None:
    last_snapshot_day = None
    last_q2: datetime | None = None
    while True:
        now = datetime.now(UTC)
        if sample_exists(settings):
            if last_snapshot_day != now.date():
                await daily.snapshots(settings, client=client)
                last_snapshot_day = now.date()
            if last_q2 is None or now - last_q2 >= Q2_EVERY:
                await daily.q2(settings, Q2_WINDOW_HOURS, Q2_MAX_MATCHES, SEED, client=client)
                last_q2 = now
        await asyncio.sleep(POLL_SECONDS)


async def supervise(settings: Settings) -> int:
    async with RiotClient(settings) as client:
        jobs = [
            asyncio.create_task(crawl(settings, client)),
            asyncio.create_task(scheduled(settings, client)),
        ]
        try:
            # The crawl finishing is normal; the scheduler runs forever. Any error ends the run.
            pending = set(jobs)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task.exception() is not None:
                        raise task.exception()
        except RiotAPIError as e:
            log(f"supervisor: stopped: {e}")
            return 2
        finally:
            for task in jobs:
                task.cancel()
    return 0


def main() -> int:
    code = asyncio.run(supervise(load_settings()))
    # An expired key exits 0 so Fly's on-failure restart policy doesn't loop on a dead key; a crash
    # (exit 1) restarts the machine and every job resumes from disk.
    return 0 if code == 2 else code


if __name__ == "__main__":
    sys.exit(main())
