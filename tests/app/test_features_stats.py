import math
import random

import pytest
from ekko_api import features, stats
from ekko_api.features import Game

from .conftest import PUUID, FakeRiot

NORMS = {"overall": {"mean": 0.0, "sd": 1000.0}, "by_tier_role_patch": {}}


def _games(riot: FakeRiot) -> list[Game]:
    out = []
    for mid in riot.ids:
        g = features.game_from_payloads(PUUID, riot.g.matches[mid], riot.g.timelines.get(mid))
        if g:
            out.append(g)
    games = features.sequence(out)
    features.standardize(games, NORMS, "GOLD")
    return games


def test_features_from_payloads():
    riot = FakeRiot(n_games=40)
    games = _games(riot)
    assert len(games) == 39  # the remake is dropped
    assert all(g.gold_diff_14 is not None for g in games)
    assert games[0].break_minutes is None and games[0].lost_prev is None
    for prev, g in zip(games, games[1:], strict=False):
        assert g.break_minutes == pytest.approx((g.start_ms - prev.end_ms) / 60_000)
        if g.break_minutes < 60:
            assert g.lost_prev == (not prev.win)
            assert g.game_number_in_session == prev.game_number_in_session + 1
            expected = (prev.session_losses_before or 0) + 1 if not prev.win else 0
            assert g.session_losses_before == expected
        else:
            assert g.lost_prev is None and g.game_number_in_session == 1
        assert g.prev_z == prev.z


def test_gold_diff_uses_the_lane_opponent_at_minute_14():
    riot = FakeRiot(n_games=5)
    mid = riot.ids[0]
    m, t = riot.g.matches[mid], riot.g.timelines[mid]
    me = next(p for p in m["info"]["participants"] if p["puuid"] == PUUID)
    opp = next(
        p
        for p in m["info"]["participants"]
        if p["teamPosition"] == me["teamPosition"] and p["teamId"] != me["teamId"]
    )
    frame = t["info"]["frames"][14]["participantFrames"]
    g = features.game_from_payloads(PUUID, m, t)
    assert (
        g.gold_diff_14
        == frame[str(me["participantId"])]["totalGold"]
        - frame[str(opp["participantId"])]["totalGold"]
    )


def _planted(beta: float, n: int = 400, seed: int = 0) -> list[Game]:
    rng = random.Random(seed)
    games, prev = [], None
    for i in range(n):
        g = Game(f"m{i}", i * 3_600_000, i * 3_600_000 + 1_800_000, 1800, True, "TOP", "16.1", 100)
        g.break_minutes = rng.choice([5.0, 30.0, 120.0])
        g.prev_won = None if prev is None else prev.win
        g.lost_prev = None if prev is None or g.break_minutes >= 60 else not prev.win
        g.prev_z = None if prev is None else prev.z
        g.z = (beta if g.prev_won is False else 0.0) + 0.2 * (g.prev_z or 0) + rng.gauss(0, 1)
        g.win = rng.random() < 1 / (1 + math.exp(-g.z))
        g.gold_diff_14 = g.z * 1000
        games.append(g)
        prev = g
    return games


def test_tilt_recovers_a_planted_effect_and_shrinks_toward_the_prior():
    games = _planted(-0.4)
    loose = stats.tilt(games, {"mean": 0.0, "sd": 10.0}, 1000)
    assert (
        abs(loose["raw"]["estimate"] + 0.4)
        < 3 * (loose["raw"]["high"] - loose["raw"]["estimate"]) / 1.96
    )
    assert loose["supported"]
    tight = stats.tilt(games, {"mean": 0.0, "sd": 0.01}, 1000)
    assert abs(tight["shrunk"]["estimate"]) < abs(loose["shrunk"]["estimate"]) / 4
    assert not tight["supported"]


def test_tilt_needs_enough_games():
    assert stats.tilt(_planted(-0.4, n=10), {"mean": 0.0, "sd": 0.1}, 1000)["supported"] is False


def test_shrink_is_precision_weighted():
    mean, sd = stats.shrink(-0.4, 0.2, 0.0, 0.2)
    assert mean == pytest.approx(-0.2) and sd == pytest.approx(0.2 / math.sqrt(2))


def test_wilson_and_stop_rule():
    low, high = stats.wilson(2, 20)
    assert 0.02 < low < 0.1 and 0.25 < high < 0.35
    games = []
    for i in range(60):  # wins only when the previous two games weren't losses
        g = Game(f"m{i}", i, i + 1, 1800, True, "TOP", "16.1", 100)
        g.session_losses_before = 2 if i % 3 == 2 else 0
        g.win = g.session_losses_before == 0
        games.append(g)
    rule = stats.stop_rule(games)
    assert rule["games"] == 20 and rule["win_rate"] == 0 and rule["supported"]


def test_matchmaking_never_claims_anything():
    m = stats.matchmaking([10.0, -20.0, 35.0, None, 5.0])
    assert m["games"] == 4 and m["low"] < m["mean_gap_lp"] < m["high"]
    assert m["supported"] is False
