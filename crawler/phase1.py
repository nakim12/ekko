"""Phase 1 crawl (PREREGISTRATION.md section 3).

    python -m crawler.phase1 sample      # stratified sample of focal players
    python -m crawler.phase1 match-ids   # each player's last 150 ranked solo match IDs
    python -m crawler.phase1 fetch       # match details and timelines -> Parquet landing zone
    python -m crawler.phase1 status      # progress
    python -m crawler.phase1 run         # sample, match-ids, fetch in order (what Fly.io runs)

Every step is resumable; rerun it after a crash or an expired key. A 401/403 stops the run cleanly
(buffers are flushed) with exit code 2. `fetch --max-docs N` stops after N documents, for short
test bursts on a development key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from crawler.config import Settings, load_settings
from crawler.riot import RiotAPIError, RiotClient
from crawler.sampler import Sampler, SampleState
from crawler.store import SegmentWriter, append_jsonl, read_jsonl, stored_ids

GAMES_PER_PLAYER = 150
KINDS = ("matches", "timelines")


def control_dir(settings: Settings) -> Path:
    return settings.raw_dir / "phase1"


def log(message: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {message}", flush=True)


def phase0_puuids(settings: Settings) -> set[str]:
    path = settings.raw_dir / "phase0" / "players.json"
    return {p["puuid"] for p in json.loads(path.read_text())} if path.exists() else set()


# --- sample ---


async def sample(settings: Settings, per_tier: int, apex: int, seed: int) -> None:
    root = control_dir(settings)
    config_path = root / "sample_config.json"
    config = {"per_tier": per_tier, "apex": apex, "seed": seed}
    if config_path.exists():
        saved = json.loads(config_path.read_text())
        if {k: saved[k] for k in config} != config:
            raise SystemExit(f"sample already started with {saved}; refusing to mix settings")
    else:
        root.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({**config, "started_at": datetime.now(UTC).isoformat()}))

    state = SampleState.load(root)
    async with RiotClient(settings) as client:
        sampler = Sampler(client, state, phase0_puuids(settings), seed)
        await sampler.run(per_tier, apex)
        log(f"sample: {len(state.players)} players, {client.request_count} requests")


# --- match ids ---


async def match_ids(settings: Settings, games: int) -> None:
    root = control_dir(settings)
    players = list(read_jsonl(root / "players.jsonl"))
    first = {r["puuid"]: r["ids"] for r in read_jsonl(root / "first_match_ids.jsonl")}
    done = {r["puuid"] for r in read_jsonl(root / "match_ids.jsonl")}
    todo = [p for p in players if p["puuid"] not in done]
    log(f"match-ids: {len(todo)} of {len(players)} players to go")

    async with RiotClient(settings) as client:
        for i, player in enumerate(todo, 1):
            puuid = player["puuid"]
            ids = list(first.get(puuid) or await client.ranked_match_ids(puuid, count=100))
            if len(ids) == 100 and games > 100:
                ids += await client.ranked_match_ids(puuid, start=100, count=games - 100)
            append_jsonl(root / "match_ids.jsonl", {"puuid": puuid, "ids": ids[:games]})
            if i % 100 == 0 or i == len(todo):
                log(f"match-ids: {i}/{len(todo)}")


# --- fetch ---


def wanted_ids(settings: Settings) -> list[str]:
    ids = {m for r in read_jsonl(control_dir(settings) / "match_ids.jsonl") for m in r["ids"]}
    return sorted(ids)


async def fetch(settings: Settings, concurrency: int, max_docs: int | None) -> int:
    root = control_dir(settings)
    missing_path = root / "missing.jsonl"
    missing = {(r["kind"], r["match_id"]) for r in read_jsonl(missing_path)}
    wanted = wanted_ids(settings)
    todo: list[tuple[str, str]] = []
    for kind in KINDS:
        have = stored_ids(settings.raw_dir, kind)
        todo += [(kind, m) for m in wanted if m not in have and (kind, m) not in missing]
    todo.sort(key=lambda km: (km[1], km[0]))  # a match and its timeline land close together
    if max_docs is not None:
        todo = todo[:max_docs]
    log(f"fetch: {len(wanted)} matches wanted, {len(todo)} documents to fetch")
    if not todo:
        return 0

    writers = {kind: SegmentWriter(settings.raw_dir, kind) for kind in KINDS}
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)
    done = 0
    started = time.monotonic()
    auth_error: RiotAPIError | None = None

    async with RiotClient(settings) as client:

        async def worker() -> None:
            nonlocal done, auth_error
            while auth_error is None:
                try:
                    kind, match_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                getter = client.match if kind == "matches" else client.timeline
                try:
                    payload = await getter(match_id)
                except RiotAPIError as e:
                    if "invalid or expired" in str(e):
                        auth_error = e
                        return
                    append_jsonl(
                        root / "errors.jsonl", {"kind": kind, "match_id": match_id, "error": str(e)}
                    )
                    continue
                if payload is None:
                    append_jsonl(missing_path, {"kind": kind, "match_id": match_id})
                else:
                    writers[kind].add(match_id, payload)
                done += 1
                if done % 500 == 0 or done == len(todo):
                    rate = done / max(time.monotonic() - started, 1e-9)
                    eta_h = (len(todo) - done) / rate / 3600 if rate else float("inf")
                    log(f"fetch: {done}/{len(todo)} ({rate:.2f}/s, ~{eta_h:.1f} h left)")

        try:
            await asyncio.gather(*(worker() for _ in range(concurrency)))
        finally:
            for w in writers.values():
                w.flush()
        log(
            f"fetch: wrote {sum(w.written for w in writers.values())} documents, "
            f"{client.request_count} requests"
        )

    if auth_error is not None:
        log(f"fetch stopped: {auth_error}")
        return 2
    return 0


# --- status ---


def status(settings: Settings) -> None:
    root = control_dir(settings)
    players = list(read_jsonl(root / "players.jsonl"))
    by_stratum: dict[str, int] = {}
    for p in players:
        by_stratum[p["stratum"]] = by_stratum.get(p["stratum"], 0) + 1
    outcomes: dict[str, int] = {}
    for d in read_jsonl(root / "sample_log.jsonl"):
        outcomes[d["outcome"]] = outcomes.get(d["outcome"], 0) + 1
    with_ids = sum(1 for _ in read_jsonl(root / "match_ids.jsonl"))
    wanted = set(wanted_ids(settings))
    print(f"players: {len(players)} {by_stratum}")
    print(f"draws: {outcomes}")
    print(f"players with match IDs: {with_ids}")
    for kind in KINDS:
        have = stored_ids(settings.raw_dir, kind) & wanted
        print(f"{kind}: {len(have)}/{len(wanted)}")
    print(f"missing (404): {sum(1 for _ in read_jsonl(root / 'missing.jsonl'))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        name: sub.add_parser(name) for name in ("sample", "match-ids", "fetch", "status", "run")
    }
    for name in ("sample", "run"):
        commands[name].add_argument("--per-tier", type=int, default=250)
        commands[name].add_argument("--apex", type=int, default=250)
        commands[name].add_argument("--seed", type=int, default=20261119)
    for name in ("match-ids", "run"):
        commands[name].add_argument("--games", type=int, default=GAMES_PER_PLAYER)
    for name in ("fetch", "run"):
        commands[name].add_argument("--concurrency", type=int, default=10)
        commands[name].add_argument("--max-docs", type=int, default=None)
    args = parser.parse_args(argv)

    settings = load_settings()
    try:
        if args.command == "status":
            status(settings)
            return 0
        if args.command in ("sample", "run"):
            asyncio.run(sample(settings, args.per_tier, args.apex, args.seed))
        if args.command in ("match-ids", "run"):
            asyncio.run(match_ids(settings, args.games))
        if args.command in ("fetch", "run"):
            return asyncio.run(fetch(settings, args.concurrency, args.max_docs))
    except RiotAPIError as e:
        log(f"stopped: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
