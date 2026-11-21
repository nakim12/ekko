"""The lookup worker: Riot ID -> games -> features -> personal report.

Stages (each reported as progress): account, rank, match list, games (match + timeline per game,
cached across lookups), matchmaking (ranks of everyone in the last 10 games), report.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from . import coach, features, stats
from .store import Store

PRIORS_PATH = Path(__file__).with_name("priors.json")
GAMES = 100
MATCHMAKING_GAMES = 10
MATCH_LP_ADJUSTMENT = 20
TIER_GROUPS = {
    "IRON": "iron_silver",
    "BRONZE": "iron_silver",
    "SILVER": "iron_silver",
    "GOLD": "gold_platinum",
    "PLATINUM": "gold_platinum",
}
LADDER_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
DIVISIONS = ["IV", "III", "II", "I"]


class LeaseLost(Exception):
    pass


class LookupFailed(Exception):
    pass


def load_priors(path: Path = PRIORS_PATH) -> dict:
    return json.loads(path.read_text())


def split_riot_id(riot_id: str) -> tuple[str, str]:
    name, sep, tag = riot_id.strip().rpartition("#")
    if not sep or not name or not tag:
        raise LookupFailed("Riot IDs look like name#tag.")
    return name, tag


def ladder_position(entry: dict | None) -> float | None:
    """Same scale as the dbt macro: Iron IV 0 LP = 0, +100 per division, +400 per tier."""
    if not entry or not entry.get("tier"):
        return None
    tier, lp = entry["tier"], entry.get("leaguePoints", 0)
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return 2800 + lp
    return LADDER_TIERS.index(tier) * 400 + DIVISIONS.index(entry.get("rank", "IV")) * 100 + lp


class Lookup:
    """One claimed job."""

    def __init__(
        self, store: Store, riot, priors: dict, job: dict, token: str, coach_client=None
    ) -> None:
        self.store, self.riot, self.priors = store, riot, priors
        self.job, self.token = job, token
        self.coach_client = coach_client

    def progress(self, stage: str, done: int = 0, total: int = 0, message: str | None = None):
        if not self.store.update(
            self.job["id"], self.token, stage=stage, done=done, total=total, message=message
        ):
            raise LeaseLost(self.job["id"])

    async def _document(self, kind: str, match_id: str) -> dict | None:
        doc = self.store.get_document(kind, match_id)
        if doc is None:
            doc = await (
                self.riot.match(match_id) if kind == "matches" else self.riot.timeline(match_id)
            )
            if doc is not None:
                self.store.put_document(kind, match_id, doc)
        return doc

    async def run(self) -> dict:
        name, tag = split_riot_id(self.job["display_riot_id"])
        self.progress("account")
        account = await self.riot.account_by_riot_id(name, tag)
        if not account:
            raise LookupFailed(f"No Riot account named {name}#{tag}.")
        puuid = account["puuid"]

        self.progress("rank")
        entry = await self.riot.ranked_entry_by_puuid(puuid)
        tier = entry["tier"] if entry else None

        self.progress("match list")
        ids = await self.riot.ranked_match_ids(puuid, count=GAMES)
        if not ids:
            raise LookupFailed("No ranked solo games found for this Riot ID.")

        games = []
        for i, match_id in enumerate(ids, 1):
            self.progress("games", i - 1, len(ids))
            match = await self._document("matches", match_id)
            timeline = await self._document("timelines", match_id) if match else None
            if match and (g := features.game_from_payloads(puuid, match, timeline)):
                games.append((g, match))
        self.progress("games", len(ids), len(ids))

        ordered = features.sequence([g for g, _ in games])
        features.standardize(ordered, self.priors["gold_norms"], tier)
        matches = {g.match_id: m for g, m in games}
        gaps = await self._matchmaking(puuid, ordered[-MATCHMAKING_GAMES:], matches)

        self.progress("report")
        report = self._report(account, entry, ordered, gaps)
        if self.coach_client is not None:
            self.progress("coach")
            result = await asyncio.to_thread(coach.coach, report, self.coach_client)
            report["coach"] = {**result.output.model_dump(), "source": result.source}
        return report

    async def _matchmaking(
        self, puuid: str, recent: list[features.Game], matches: dict
    ) -> list[float | None]:
        ranks: dict[str, float | None] = {}
        gaps = []
        for i, g in enumerate(recent):
            self.progress("matchmaking", i, len(recent))
            parts = matches[g.match_id]["info"]["participants"]
            for p in parts:
                if p["puuid"] != puuid and p["puuid"] not in ranks:
                    ranks[p["puuid"]] = ladder_position(
                        await self.riot.ranked_entry_by_puuid(p["puuid"])
                    )

            def at_match(p):  # remove this game's result, as in the study (section 4.4)
                lp = ranks.get(p["puuid"])
                return None if lp is None else lp - MATCH_LP_ADJUSTMENT * (1 if p["win"] else -1)

            allies = [
                x
                for p in parts
                if p["teamId"] == g.team_id and p["puuid"] != puuid
                if (x := at_match(p)) is not None
            ]
            enemies = [
                x for p in parts if p["teamId"] != g.team_id if (x := at_match(p)) is not None
            ]
            ok = len(allies) >= 3 and len(enemies) >= 4
            gaps.append(sum(allies) / len(allies) - sum(enemies) / len(enemies) if ok else None)
        return gaps

    def _report(self, account: dict, entry: dict | None, games: list[features.Game], gaps) -> dict:
        tier = entry["tier"] if entry else None
        group = TIER_GROUPS.get(tier, "emerald_plus") if tier else None
        prior = self.priors["tilt_by_tier_group"][group or "gold_platinum"]
        gold_sd = self.priors["gold_norms"]["overall"]["sd"]
        return {
            "riot_id": f"{account.get('gameName', '')}#{account.get('tagLine', '')}",
            "generated_at": datetime.now(UTC).isoformat(),
            "rank": {
                "tier": tier,
                "division": entry.get("rank") if entry else None,
                "league_points": entry.get("leaguePoints") if entry else None,
            },
            "tier_group": group,
            "games_analyzed": len(games),
            "priors_are_placeholders": bool(self.priors.get("placeholder")),
            "tilt": stats.tilt(games, prior, gold_sd),
            "cooldown": stats.cooldown(games),
            "stop_rule": stats.stop_rule(games),
            "matchmaking": stats.matchmaking(gaps),
            "history": [
                {
                    "start_ms": g.start_ms,
                    "win": g.win,
                    "session": g.game_number_in_session == 1,
                    "z": None if g.z is None or math.isnan(g.z) else round(g.z, 3),
                }
                for g in games
            ],
        }


async def process(
    store: Store, riot, priors: dict, job: dict, token: str, coach_client=None
) -> None:
    lookup = Lookup(store, riot, priors, job, token, coach_client)
    try:
        report = await lookup.run()
        report_id = store.save_report(job["display_riot_id"], report)
        store.finish(job["id"], token, "done", stage="done", report_id=report_id)
    except LeaseLost:
        return  # another worker owns this job now; write nothing
    except LookupFailed as e:
        store.finish(job["id"], token, "failed", stage="failed", message=str(e))
    except Exception as e:  # keep the worker alive; surface a generic error
        store.finish(
            job["id"],
            token,
            "failed",
            stage="failed",
            message=f"Lookup failed ({type(e).__name__}).",
        )


async def worker_loop(
    store: Store, riot, priors: dict, poll_seconds: float = 0.5, coach_client=None
) -> None:
    while True:
        claimed = store.claim()
        if claimed is None:
            await asyncio.sleep(poll_seconds)
            continue
        await process(store, riot, priors, *claimed, coach_client=coach_client)
