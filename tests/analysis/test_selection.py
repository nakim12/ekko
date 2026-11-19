import numpy as np
import pytest
from ekko_analysis import q1, selection
from ekko_analysis.inference import Estimate
from ekko_analysis.simulate import simulate_player_games


def test_continuation_recovers_planted_difference():
    df = simulate_player_games(
        n_players=300,
        games_per_player=100,
        p_continue_after_win=0.65,
        p_continue_after_loss=0.5,
        seed=7,
    )
    res = selection.fit_continuation(df)
    assert abs(res.loss_effect.estimate + 0.15) < 3 * res.loss_effect.se
    assert res.stop_rate_after_loss == pytest.approx(0.5, abs=0.02)
    assert res.stop_rate_after_win == pytest.approx(0.35, abs=0.02)


def test_ipw_without_selection_matches_unweighted():
    df = simulate_player_games(n_players=300, games_per_player=100, beta=-0.1, seed=8)
    df["ipw"] = selection.ipw_weights(df)
    h1 = df["q1_eligible"].astype(bool)
    assert df.loc[h1, "ipw"].notna().all()
    assert (df.loc[h1, "ipw"] >= 1).all()
    weighted, plain = q1.fit_h1(df, weights="ipw"), q1.fit_h1(df)
    assert abs(weighted.estimate - plain.estimate) < plain.se


def _estimate(est, lo, hi):
    return Estimate("H1", est, 0.01, lo, hi, 0.001, 1000, 100)


def test_selection_bound():
    b = selection.selection_bound(_estimate(-0.05, -0.07, -0.03), stop_rate_after_loss=0.4)
    assert b.delta == pytest.approx(0.075)  # -(-0.03) / 0.4
    assert "better" in b.explanation
    assert selection.selection_bound(_estimate(-0.01, -0.03, 0.01), 0.4).delta is None
    assert np.sign(selection.selection_bound(_estimate(0.05, 0.03, 0.07), 0.5).delta) == -1
