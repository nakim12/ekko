"""A small synthetic warehouse in the shape of the real raw schema, for CI's dbt build.

    python -m tests.fixtures.synthetic_warehouse /tmp/ekko-ci.duckdb

Real Riot data never goes into git, so CI builds dbt on this instead. Payloads mimic match-v5
match and timeline responses (only the fields the models read) and cover the cases the models and
tests care about: sessions and breaks, a remake, games shorter than 14 minutes, Q2 matches with
focal, placebo and autofill histories, and daily rank snapshots. Both the Phase 0 tables and the
Phase 1 tables are written, so `dbt build` and `dbt build --vars '{phase: 1}'` both run.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
TIERS = ["IRON", "SILVER", "GOLD", "EMERALD", "DIAMOND", "MASTER"]
MINUTE = 60_000


class Generator:
    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.n_matches = 0
        self.n_others = 0
        self.matches: dict[str, dict] = {}
        self.timelines: dict[str, dict] = {}

    def other(self) -> str:
        self.n_others += 1
        return f"other-{self.n_others:05d}"

    def match(
        self,
        start: datetime,
        players: dict[str, tuple[int, str]],
        minutes: float,
        blue_wins: bool,
        timeline: bool = True,
        remake: bool = False,
    ) -> str:
        """A ranked solo match. `players` maps puuid -> (team_id, role) for some participants; the
        rest are filled with new non-focal players."""
        self.n_matches += 1
        match_id = f"NA1_{9_000_000 + self.n_matches}"
        seats = {(team, role): None for team in (100, 200) for role in ROLES}
        for puuid, seat in players.items():
            seats[seat] = puuid
        participants = []
        for pid, ((team, role), puuid) in enumerate(seats.items(), start=1):
            r = self.rng
            participants.append(
                {
                    "participantId": pid,
                    "puuid": puuid or self.other(),
                    "teamId": team,
                    "teamPosition": role,
                    "championId": r.randint(1, 60),
                    "championName": f"Champ{r.randint(1, 60)}",
                    "win": (team == 100) == blue_wins,
                    "kills": r.randint(0, 12),
                    "deaths": r.randint(0, 10),
                    "assists": r.randint(0, 15),
                    "totalMinionsKilled": r.randint(0, 250),
                    "neutralMinionsKilled": r.randint(0, 120),
                    "goldEarned": r.randint(4000, 16000),
                    "totalDamageDealtToChampions": r.randint(2000, 40000),
                    "visionScore": r.randint(0, 80),
                    "timePlayed": int(minutes * 60),
                    "gameEndedInEarlySurrender": remake,
                    "gameEndedInSurrender": remake,
                }
            )
        start_ms = int(start.timestamp() * 1000)
        end_ms = start_ms + int(minutes * MINUTE)
        self.matches[match_id] = {
            "metadata": {"matchId": match_id, "participants": [p["puuid"] for p in participants]},
            "info": {
                "gameStartTimestamp": start_ms,
                "gameEndTimestamp": end_ms,
                "gameDuration": int(minutes * 60),
                "gameVersion": f"16.{self.rng.choice([2, 3])}.512.7000",
                "queueId": 420,
                "platformId": "NA1",
                "endOfGameResult": "GameComplete",
                "participants": participants,
            },
        }
        if timeline:
            self.timelines[match_id] = self._timeline(match_id, minutes)
        return match_id

    def _timeline(self, match_id: str, minutes: float) -> dict:
        frames = []
        n_full = int(minutes)
        for i in range(n_full + 1):
            ts = i * MINUTE + self.rng.randint(0, 900) if i else 0
            frames.append(self._frame(ts, i))
        frames.append(self._frame(int(minutes * MINUTE), minutes))  # end of game
        return {
            "metadata": {"matchId": match_id},
            "info": {"frameInterval": MINUTE, "frames": frames},
        }

    def _frame(self, ts: int, minute: float) -> dict:
        r = self.rng
        pf = {
            str(i): {
                "totalGold": int(500 + minute * r.randint(250, 450)),
                "xp": int(minute * r.randint(350, 600)),
                "level": max(1, int(minute // 2)),
                "minionsKilled": int(minute * r.randint(0, 9)),
                "jungleMinionsKilled": int(minute * r.randint(0, 5)),
            }
            for i in range(1, 11)
        }
        events = [
            {
                "type": "CHAMPION_KILL",
                "timestamp": ts - r.randint(0, 50_000),
                "killerId": r.randint(1, 10),
                "victimId": r.randint(1, 10),
            }
            for _ in range(r.randint(0, 2))
            if ts > MINUTE
        ]
        return {"timestamp": ts, "participantFrames": pf, "events": events}


def build(path: Path, n_players: int = 6, games: int = 40, seed: int = 0) -> None:
    g = Generator(seed)
    rng = g.rng
    players, player_match_ids, snapshots = [], [], []
    q2_matches, q2_ranks, q2_history = [], [], []
    base = datetime(2026, 11, 1, 18, tzinfo=UTC)

    for i in range(n_players):
        puuid = f"focal-{i:03d}"
        tier = TIERS[i % len(TIERS)]
        division = "I" if tier == "MASTER" else rng.choice(["I", "II", "III", "IV"])
        players.append(
            {
                "puuid": puuid,
                "stratum": tier,
                "tier": tier,
                "division": division,
                "league_points": rng.randint(0, 99),
                "wins": 50,
                "losses": 50,
            }
        )
        role = ROLES[i % 5]
        clock = base + timedelta(hours=i)
        ids = []
        for k in range(games):
            minutes = 2.5 if k == 5 else 12.0 if k == 9 else rng.uniform(18, 38)
            ids.append(
                g.match(
                    clock,
                    {puuid: (rng.choice([100, 200]), role)},
                    minutes,
                    rng.random() < 0.5,
                    remake=(k == 5),
                )
            )
            clock += timedelta(minutes=minutes) + timedelta(
                minutes=rng.uniform(2, 50) if rng.random() < 0.6 else rng.uniform(70, 2000)
            )
        player_match_ids += [{"puuid": puuid, "match_id": m} for m in ids]
        for day in range(3):
            snapshots.append(
                {
                    "puuid": puuid,
                    "snapshot_at": base + timedelta(days=day, hours=6),
                    "found": True,
                    "tier": tier,
                    "rank": division,
                    "league_points": rng.randint(0, 99),
                    "wins": 50,
                    "losses": 50,
                }
            )

        # One Q2 match per focal player, after their crawled history. Its previous games are
        # their last crawled ones; the placebo and (first player only) autofill players get their
        # own previous matches.
        start = clock + timedelta(hours=1)
        q2_id = g.match(start, {puuid: (100, role)}, 30, rng.random() < 0.5, timeline=False)
        info = g.matches[q2_id]["info"]
        others = [p for p in info["participants"] if p["puuid"] != puuid]
        placebo = rng.choice(others)
        autofill = i == 0
        game_end = datetime.fromtimestamp(info["gameEndTimestamp"] / 1000, UTC)
        q2_matches.append(
            {
                "match_id": q2_id,
                "status": "qualified",
                "focal_puuid": puuid,
                "placebo_puuid": placebo["puuid"],
                "autofill_sample": autofill,
                "game_end_at": game_end,
                "ranks_looked_up_at": game_end + timedelta(hours=3),
                "processed_at": game_end + timedelta(hours=3),
            }
        )
        for p in info["participants"]:
            unranked = p["puuid"] != puuid and rng.random() < 0.1
            t = rng.choice(TIERS[:-1])
            q2_ranks.append(
                {
                    "match_id": q2_id,
                    "puuid": p["puuid"],
                    "looked_up_at": game_end + timedelta(hours=3),
                    "found": not unranked,
                    "tier": None if unranked else t,
                    "rank": None if unranked else rng.choice(["I", "II", "III", "IV"]),
                    "league_points": None if unranked else rng.randint(0, 99),
                    "wins": None,
                    "losses": None,
                }
            )
        q2_history.append(
            {
                "match_id": q2_id,
                "puuid": puuid,
                "purpose": "focal",
                "previous_match_ids": ids[::-1][:5],
            }
        )
        history_players = [(placebo, "placebo", 5)] + (
            [(p, "autofill", 20) for p in others] if autofill else []
        )
        for p, purpose, n in history_players:
            before = start - timedelta(hours=2)
            prev = []
            # About half the autofill-history players usually play another role (likely autofilled).
            usual = p["teamPosition"]
            if purpose == "autofill" and rng.random() < 0.5:
                usual = rng.choice([r for r in ROLES if r != usual])
            for _ in range(n):
                main = usual if rng.random() < 0.8 else rng.choice(ROLES)
                before -= timedelta(minutes=45)
                prev.append(
                    g.match(
                        before, {p["puuid"]: (100, main)}, 30, rng.random() < 0.5, timeline=False
                    )
                )
            q2_history.append(
                {
                    "match_id": q2_id,
                    "puuid": p["puuid"],
                    "purpose": purpose,
                    "previous_match_ids": prev,
                }
            )

    path.unlink(missing_ok=True)
    with duckdb.connect(str(path)) as con:
        con.execute("create schema raw")
        for name, docs in [("matches", g.matches), ("timelines", g.timelines)]:
            con.register(
                "t",
                pa.table(
                    {"match_id": list(docs), "payload": [json.dumps(d) for d in docs.values()]}
                ),
            )
            con.execute(
                f"create table raw.{name} as select match_id, payload::json as payload from t"
            )
            con.unregister("t")
        tables = {
            "phase0_players": players,
            "players": players,
            "phase0_player_match_ids": player_match_ids,
            "player_match_ids": player_match_ids,
            "rank_snapshots": snapshots,
            "q2_matches": q2_matches,
            "q2_ranks": q2_ranks,
        }
        for name, rows in tables.items():
            con.register("t", pa.Table.from_pylist(rows))
            con.execute(f"create table raw.{name} as select * from t")
            con.unregister("t")
        con.register("t", pa.Table.from_pylist(q2_history))
        con.execute("create table raw.q2_history as select * from t")
        con.unregister("t")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ekko-ci.duckdb")
    build(out)
    print(f"wrote {out}")
