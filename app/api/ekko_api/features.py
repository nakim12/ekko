"""One player's game features from raw match-v5 payloads, for live lookups.

The same definitions as the dbt models (analysis/PREREGISTRATION.md section 4): remakes dropped,
lane opponent by teamPosition, gold/CS/XP differences at the minute-14 frame, AFK at under 1,500 XP,
sessions split at breaks of 60+ minutes, previous result within the session, and consecutive
in-session losses. `tests/app/test_features.py` checks this against dbt on synthetic data.

Standardizing uses population norms (mean and SD of gold_diff_14 per tier x role x patch) from
priors.json, since one player's games can't define "normal" for their tier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MINUTE_MARK = 14
MINUTE_MS = 60_000
REMAKE_SECONDS = 300
AFK_XP = 1500
SESSION_GAP_MINUTES = 60
RANKED_SOLO = 420


@dataclass
class Game:
    match_id: str
    start_ms: int
    end_ms: int
    duration_s: int
    win: bool
    role: str | None
    patch: str
    team_id: int
    gold_diff_14: float | None = None
    cs_diff_14: float | None = None
    afk: bool = False
    # sequence features (filled by `sequence`)
    break_minutes: float | None = None
    game_number_in_session: int = 1
    lost_prev: bool | None = None  # previous game in the same session was a loss
    prev_won: bool | None = None  # previous game, any time
    session_losses_before: int | None = None
    z: float | None = None
    prev_z: float | None = None

    @property
    def outcome_eligible(self) -> bool:
        return self.gold_diff_14 is not None and not self.afk


def _minute_frame(timeline: dict) -> dict | None:
    frames = timeline.get("info", {}).get("frames", [])
    if len(frames) > MINUTE_MARK and frames[MINUTE_MARK]["timestamp"] >= MINUTE_MARK * MINUTE_MS:
        return frames[MINUTE_MARK]["participantFrames"]
    return None


def game_from_payloads(puuid: str, match: dict, timeline: dict | None) -> Game | None:
    """The player's game, or None for remakes, other queues, or if they're not in it."""
    info = match["info"]
    if info.get("queueId") != RANKED_SOLO:
        return None
    parts = info["participants"]
    me = next((p for p in parts if p["puuid"] == puuid), None)
    if me is None:
        return None
    if info["gameDuration"] < REMAKE_SECONDS or any(
        p.get("gameEndedInEarlySurrender") for p in parts
    ):
        return None
    version = info.get("gameVersion", "")
    game = Game(
        match_id=match["metadata"]["matchId"],
        start_ms=info["gameStartTimestamp"],
        end_ms=info["gameEndTimestamp"],
        duration_s=info["gameDuration"],
        win=bool(me["win"]),
        role=me.get("teamPosition") or None,
        patch=".".join(version.split(".")[:2]),
        team_id=me["teamId"],
    )
    same = [p for p in parts if game.role and p.get("teamPosition") == game.role]
    mine = [p for p in same if p["teamId"] == game.team_id]
    theirs = [p for p in same if p["teamId"] != game.team_id]
    frame = _minute_frame(timeline) if timeline else None
    if frame is not None:
        f = frame[str(me["participantId"])]
        if len(mine) == 1 and len(theirs) == 1:
            o = frame[str(theirs[0]["participantId"])]
            game.gold_diff_14 = f["totalGold"] - o["totalGold"]
            game.cs_diff_14 = (f["minionsKilled"] + f["jungleMinionsKilled"]) - (
                o["minionsKilled"] + o["jungleMinionsKilled"]
            )
            game.afk = f["xp"] < AFK_XP or o["xp"] < AFK_XP
        else:
            game.afk = f["xp"] < AFK_XP
    return game


def sequence(games: list[Game], gap: float = SESSION_GAP_MINUTES) -> list[Game]:
    """Order games and fill sessions, previous results and in-session loss runs."""
    games = sorted(games, key=lambda g: (g.start_ms, g.match_id))
    prev: Game | None = None
    for g in games:
        if prev is None:
            g.break_minutes = None
            new_session = True
        else:
            g.break_minutes = (g.start_ms - prev.end_ms) / MINUTE_MS
            new_session = g.break_minutes >= gap
            g.prev_won = prev.win
            g.prev_z = prev.z
        if new_session:
            g.game_number_in_session = 1
            g.lost_prev = None
            g.session_losses_before = None
        else:
            g.game_number_in_session = prev.game_number_in_session + 1
            g.lost_prev = not prev.win
            # consecutive in-session losses ending with the previous game
            g.session_losses_before = (prev.session_losses_before or 0) + 1 if not prev.win else 0
        prev = g
    return games


def standardize(games: list[Game], norms: dict, tier: str | None) -> None:
    """z for each eligible game from population norms; prev_z follows from the sequence."""
    by_key = norms.get("by_tier_role_patch", {})
    overall = norms["overall"]
    for g in games:
        if not g.outcome_eligible:
            g.z = None
            continue
        n = by_key.get(f"{tier}|{g.role}|{g.patch}") or by_key.get(f"{tier}|{g.role}") or overall
        g.z = (g.gold_diff_14 - n["mean"]) / n["sd"] if n["sd"] else None
    for prev, g in zip([None, *games[:-1]], games, strict=True):
        g.prev_z = prev.z if prev is not None else None


def log_break(g: Game) -> float:
    return math.log1p(max(g.break_minutes or 0.0, 0.0))
