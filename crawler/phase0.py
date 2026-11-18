"""Phase 0: pull a small sample and confirm the fields the data model needs.

    python -m crawler.phase0 fetch   # sample players, fetch ranked match IDs, matches, timelines
    python -m crawler.phase0 load    # landing files -> Parquet -> DuckDB
    python -m crawler.phase0 check   # field check report -> docs/phase0-field-check.md

fetch is resumable: anything already on disk is skipped, so rerun it after a key expires.
The player sample here is a convenience sample (page 1 of one random division per tier), not
the stratified sample from the plan.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import random
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from crawler.config import APEX_TIERS, DIVISIONS, Settings, load_settings
from crawler.riot import RiotClient

SAMPLE_TIERS = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", *APEX_TIERS)
POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
MINUTE_MS = 60_000


def landing_dir(settings: Settings) -> Path:
    return settings.raw_dir / "phase0"


def write_json_gz(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.rename(path)  # atomic, so a killed run never leaves a half-written file


def read_json_gz(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# --- fetch ---


async def sample_players(client: RiotClient, per_tier: int, rng: random.Random) -> list[dict]:
    players = []
    for tier in SAMPLE_TIERS:
        if tier in APEX_TIERS:
            entries = await client.apex_league(tier)
            division = "I"
        else:
            division = rng.choice(DIVISIONS)
            entries = await client.league_entries(tier, division)
        active = [e for e in entries if not e.get("inactive") and e.get("puuid")]
        for entry in rng.sample(active, min(per_tier, len(active))):
            players.append(
                {
                    "puuid": entry["puuid"],
                    "tier": tier,
                    "division": division if tier not in APEX_TIERS else entry.get("rank", "I"),
                    "league_points": entry["leaguePoints"],
                    "wins": entry["wins"],
                    "losses": entry["losses"],
                }
            )
    return players


async def fetch(settings: Settings, per_tier: int, games: int, seed: int) -> None:
    root = landing_dir(settings)
    players_path = root / "players.json"

    async with RiotClient(settings) as client:
        if players_path.exists():
            players = json.loads(players_path.read_text())
        else:
            players = await sample_players(client, per_tier, random.Random(seed))
            root.mkdir(parents=True, exist_ok=True)
            players_path.write_text(json.dumps(players, indent=1))
        print(f"{len(players)} players", flush=True)

        match_ids: list[str] = []
        for player in players:
            ids_path = root / "match_ids" / f"{player['puuid']}.json"
            if ids_path.exists():
                ids = json.loads(ids_path.read_text())
            else:
                ids = await client.ranked_match_ids(player["puuid"], count=games)
                ids_path.parent.mkdir(parents=True, exist_ok=True)
                ids_path.write_text(json.dumps(ids))
            match_ids.extend(ids)
        unique_ids = sorted(set(match_ids))
        print(f"{len(match_ids)} player-games, {len(unique_ids)} unique matches", flush=True)

        todo = [
            (kind, match_id)
            for match_id in unique_ids
            for kind in ("matches", "timelines")
            if not (root / kind / f"{match_id}.json.gz").exists()
        ]
        print(f"{len(todo)} documents to fetch", flush=True)

        done = 0
        semaphore = asyncio.Semaphore(10)

        async def fetch_one(kind: str, match_id: str) -> None:
            nonlocal done
            async with semaphore:
                getter = client.match if kind == "matches" else client.timeline
                payload = await getter(match_id)
                if payload is not None:
                    write_json_gz(root / kind / f"{match_id}.json.gz", payload)
                done += 1
                if done % 100 == 0 or done == len(todo):
                    stamp = datetime.now(UTC).strftime("%H:%M:%S")
                    print(f"[{stamp}] {done}/{len(todo)}", flush=True)

        await asyncio.gather(*(fetch_one(kind, match_id) for kind, match_id in todo))
        print(f"done, {client.request_count} requests", flush=True)


# --- load ---


def load(settings: Settings) -> None:
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    root = landing_dir(settings)
    dt = datetime.now(UTC).date().isoformat()
    con = duckdb.connect(str(settings.duckdb_path))
    con.execute("create schema if not exists raw")

    for kind in ("matches", "timelines"):
        files = sorted((root / kind).glob("*.json.gz"))
        table = pa.table(
            {
                "match_id": [f.name.removesuffix(".json.gz") for f in files],
                "payload": [gzip.open(f, "rt", encoding="utf-8").read() for f in files],
            }
        )
        out = settings.raw_dir / kind / f"dt={dt}" / "phase0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out, compression="zstd")
        con.execute(
            f"create or replace table raw.{kind} as "
            f"select match_id, payload::json as payload from read_parquet('{out}')"
        )
        count = con.execute(f"select count(*) from raw.{kind}").fetchone()[0]
        print(f"raw.{kind}: {count} rows ({out})")

    players = json.loads((root / "players.json").read_text())
    con.execute(
        "create or replace table raw.phase0_players as select * from read_json_auto(?)",
        [str(root / "players.json")],
    )
    print(f"raw.phase0_players: {len(players)} rows")
    con.close()


# --- check ---


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def check(settings: Settings, report_path: Path) -> None:
    root = landing_dir(settings)
    players = json.loads((root / "players.json").read_text())
    tier_of = {p["puuid"]: p["tier"] for p in players}

    match_fields = ("gameStartTimestamp", "gameEndTimestamp", "gameDuration", "gameVersion")
    participant_fields = (
        "puuid",
        "teamId",
        "teamPosition",
        "win",
        "championId",
        "kills",
        "deaths",
        "assists",
        "totalMinionsKilled",
        "neutralMinionsKilled",
        "goldEarned",
        "totalDamageDealtToChampions",
        "visionScore",
        "timePlayed",
        "gameEndedInEarlySurrender",
        "gameEndedInSurrender",
    )
    frame_fields = ("totalGold", "xp", "minionsKilled", "jungleMinionsKilled")

    c: Counter = Counter()
    positions: Counter = Counter()
    gold_diffs: list[float] = []
    focal_games: dict[str, list[tuple[int, int]]] = {}

    match_files = sorted((root / "matches").glob("*.json.gz"))
    for path in match_files:
        match = read_json_gz(path)
        info = match["info"]
        c["matches"] += 1
        c["queue_420"] += info.get("queueId") == 420
        for field in match_fields:
            c[f"match.{field}"] += info.get(field) is not None
        parts = info["participants"]
        c["ten_participants"] += len(parts) == 10
        c["five_per_team"] += Counter(p["teamId"] for p in parts) == Counter({100: 5, 200: 5})
        c["one_winning_team"] += sum(t["win"] for t in info["teams"]) == 1
        duration_s = info["gameDuration"]
        c["remake_under_5min"] += duration_s < 300
        c["at_least_14min"] += duration_s >= 14 * 60

        for p in parts:
            c["participants"] += 1
            for field in participant_fields:
                c[f"participant.{field}"] += p.get(field) not in (None, "")
            positions[p.get("teamPosition") or "(empty)"] += 1
        by_team = {
            team: sorted(p.get("teamPosition", "") for p in parts if p["teamId"] == team)
            for team in (100, 200)
        }
        lanes_ok = all(by_team[team] == sorted(POSITIONS) for team in (100, 200))
        c["lane_opponents_matchable"] += lanes_ok

        for p in parts:
            if p["puuid"] in tier_of:
                focal_games.setdefault(p["puuid"], []).append(
                    (info["gameStartTimestamp"], info["gameEndTimestamp"])
                )

        timeline_path = root / "timelines" / path.name
        if not timeline_path.exists():
            continue
        timeline = read_json_gz(timeline_path)
        tinfo = timeline["info"]
        c["timelines"] += 1
        c["frame_interval_60s"] += tinfo.get("frameInterval") == MINUTE_MS
        c["timeline_participants_align"] += (
            timeline["metadata"]["participants"] == match["metadata"]["participants"]
        )
        frames = tinfo["frames"]
        if duration_s < 14 * 60:
            continue
        c["timelines_14min_game"] += 1
        if len(frames) <= 14:
            continue
        c["frame_14_exists"] += 1
        frame = frames[14]["participantFrames"]
        c["frame_14_all_fields"] += all(
            all(frame[str(i)].get(f) is not None for f in frame_fields) for i in range(1, 11)
        )
        has_kill_events = any(
            e.get("type") == "CHAMPION_KILL" and "victimId" in e
            for f in frames[:15]
            for e in f["events"]
        )
        c["kill_events_before_14"] += has_kill_events
        if lanes_ok:
            pid = {p["participantId"]: p for p in parts}
            for i in range(1, 11):
                me = pid[i]
                if me["puuid"] not in tier_of:
                    continue
                opp = next(
                    p
                    for p in parts
                    if p["teamId"] != me["teamId"] and p["teamPosition"] == me["teamPosition"]
                )
                gold_diffs.append(
                    frame[str(i)]["totalGold"] - frame[str(opp["participantId"])]["totalGold"]
                )

    gaps_min: list[float] = []
    for games in focal_games.values():
        games.sort()
        for (_, prev_end), (start, _) in zip(games, games[1:], strict=False):
            gaps_min.append((start - prev_end) / MINUTE_MS)
    under_60 = sum(0 <= g < 60 for g in gaps_min)
    negative = sum(g < 0 for g in gaps_min)

    n, n_p, n_t, n_t14 = c["matches"], c["participants"], c["timelines"], c["timelines_14min_game"]
    games_per_player = [len(g) for g in focal_games.values()]
    tier_counts = ", ".join(f"{t} {k}" for t, k in Counter(tier_of.values()).items())
    lines = [
        "# Phase 0 field check",
        "",
        f"Generated by `python -m crawler.phase0 check` on {datetime.now(UTC):%Y-%m-%d}. "
        "Aggregate counts only; no player identifiers.",
        "",
        "## Sample",
        "",
        f"- Players: {len(players)} ({tier_counts})",
        f"- Matches: {n}; timelines: {n_t}",
        f"- Focal player-games: {sum(games_per_player)} across {len(games_per_player)} players; "
        f"per player min {min(games_per_player, default=0)}, "
        f"median {statistics.median(games_per_player) if games_per_player else 0}, "
        f"max {max(games_per_player, default=0)}",
        "",
        "## Match structure",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Queue 420 | {pct(c['queue_420'], n)} |",
        f"| Exactly 10 participants | {pct(c['ten_participants'], n)} |",
        f"| 5 per team | {pct(c['five_per_team'], n)} |",
        f"| Exactly one winning team | {pct(c['one_winning_team'], n)} |",
        f"| Remakes (< 5 min) | {pct(c['remake_under_5min'], n)} |",
        f"| Game length ≥ 14 min | {pct(c['at_least_14min'], n)} |",
        f"| Both teams have one TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY (lane opponents matchable) "
        f"| {pct(c['lane_opponents_matchable'], n)} |",
        *[f"| `info.{f}` present | {pct(c[f'match.{f}'], n)} |" for f in match_fields],
        "",
        "## Participant fields",
        "",
        "| Field | Present |",
        "|---|---|",
        *[f"| `{f}` | {pct(c[f'participant.{f}'], n_p)} |" for f in participant_fields],
        "",
        "`teamPosition` distribution: "
        + ", ".join(f"{k} {pct(v, n_p)}" for k, v in positions.most_common()),
        "",
        "## Timelines",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Frame interval is 60 s | {pct(c['frame_interval_60s'], n_t)} |",
        "| Timeline participant order matches match "
        f"| {pct(c['timeline_participants_align'], n_t)} |",
        f"| Minute-14 frame exists (games ≥ 14 min) | {pct(c['frame_14_exists'], n_t14)} |",
        f"| Minute-14 frame has {', '.join(f'`{f}`' for f in frame_fields)} for all 10 "
        f"| {pct(c['frame_14_all_fields'], n_t14)} |",
        "| `CHAMPION_KILL` events with `victimId` before 14 "
        f"| {pct(c['kill_events_before_14'], n_t14)} |",
        "",
        f"Focal `gold_diff_at_14` vs lane opponent: n={len(gold_diffs)}"
        + (
            f", mean {statistics.mean(gold_diffs):.0f}, sd {statistics.stdev(gold_diffs):.0f}"
            if len(gold_diffs) > 1
            else ""
        ),
        "",
        "## Sessions",
        "",
        f"- Gaps between a focal player's consecutive ranked games: {len(gaps_min)}",
        f"- Under 60 min (same session at the default threshold): {pct(under_60, len(gaps_min))}",
        f"- Negative gaps (overlapping timestamps, should be 0): {negative}",
        f"- Median gap: {statistics.median(gaps_min):.0f} min" if gaps_min else "- Median gap: n/a",
        "",
    ]
    report_path.write_text("\n".join(lines))
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--per-tier", type=int, default=2)
    fetch_parser.add_argument("--games", type=int, default=100)
    fetch_parser.add_argument("--seed", type=int, default=0)
    sub.add_parser("load")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--report", type=Path, default=Path("docs/phase0-field-check.md"))
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.command == "fetch":
        asyncio.run(fetch(settings, args.per_tier, args.games, args.seed))
    elif args.command == "load":
        load(settings)
    else:
        check(settings, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
