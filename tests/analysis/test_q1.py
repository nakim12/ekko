"""Q1 models recover planted tilt and hold their false-positive rate (PREREGISTRATION.md 9)."""

import numpy as np
from ekko_analysis import q1
from ekko_analysis.simulate import simulate_player_games

REALISTIC = dict(gamma=0.2, short_game_rate=0.05, session_form_sd=0.3)


def test_h1_recovers_planted_effect():
    df = simulate_player_games(n_players=300, games_per_player=100, beta=-0.1, seed=11, **REALISTIC)
    est = q1.fit_h1(df)
    assert abs(est.estimate + 0.1) < 3 * est.se
    assert est.ci_low < -0.1 < est.ci_high


def test_h1_holds_false_positive_rate_under_null():
    estimates, rejections = [], []
    for seed in range(30):
        df = simulate_player_games(
            n_players=150, games_per_player=80, beta=0.0, seed=100 + seed, **REALISTIC
        )
        est = q1.fit_h1(df)
        estimates.append(est.estimate)
        rejections.append(est.p_value < 0.05)
    assert abs(np.mean(estimates)) < 0.01
    assert np.mean(rejections) <= 0.15


def test_registered_fill_lag_is_biased_toward_tilt():
    """Why Deviation 1 exists: with missing lags filled, a true zero effect reads as tilt."""
    fill, drop = [], []
    for seed in range(10):
        df = simulate_player_games(
            n_players=300, games_per_player=120, beta=0.0, seed=200 + seed, **REALISTIC
        )
        fill.append(q1.fit_h1(df, lag="fill").estimate)
        drop.append(q1.fit_h1(df, lag="drop").estimate)
    assert np.mean(fill) < -0.01
    assert np.mean(fill) < np.mean(drop) - 0.01


def test_h1_secondary_outcomes_run():
    df = simulate_player_games(n_players=100, games_per_player=60, beta=-0.2, seed=3)
    for outcome in q1.SECONDARY:
        est = q1.fit_h1(df, outcome=outcome)
        assert np.isfinite(est.estimate) and est.n_obs > 0


def test_h1a_constant_effect_has_no_trend():
    df = simulate_player_games(n_players=300, games_per_player=100, beta=-0.15, seed=4, **REALISTIC)
    res = q1.fit_h1a(df)
    for est in res.effects.values():
        assert abs(est.estimate + 0.15) < 3 * est.se
    assert abs(res.trend.estimate) < 3 * res.trend.se


def test_h1b_detects_effect_limited_to_the_session():
    # The simulator applies tilt only within a session, so breaks of 1 h+ should show none.
    df = simulate_player_games(n_players=300, games_per_player=100, beta=-0.25, seed=5, **REALISTIC)
    res = q1.fit_h1b(df)
    for bucket in ["lt_15m", "15_60m"]:
        assert abs(res.effects[bucket].estimate + 0.25) < 3 * res.effects[bucket].se
    for bucket in ["1_6h", "6_24h"]:
        assert abs(res.effects[bucket].estimate) < 3 * res.effects[bucket].se
    assert res.joint_test.p_value < 0.01


def test_h1c_detects_tier_differences():
    by_tier = {"iron_silver": -0.3, "gold_platinum": -0.1, "emerald_plus": 0.0}
    df = simulate_player_games(n_players=300, games_per_player=100, beta_by_tier=by_tier, seed=6)
    res = q1.fit_h1c(df)
    for group, beta in by_tier.items():
        assert abs(res.effects[group].estimate - beta) < 3 * res.effects[group].se
    assert res.joint_test.p_value < 0.01
