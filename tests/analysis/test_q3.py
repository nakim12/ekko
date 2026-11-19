import numpy as np
from ekko_analysis import q3
from ekko_analysis.simulate import simulate_sequences


def test_count_runs():
    assert q3.count_runs(np.array([1, 1, 0, 0, 0, 1])) == 3
    assert q3.count_runs(np.array([1, 0, 1, 0])) == 4
    assert list(q3.count_runs(np.array([[1, 1], [0, 1]]))) == [1, 2]


def test_local_win_rate_excludes_the_game_itself():
    seq = np.array([1, 0, 0, 0, 0])
    p = q3.local_win_rate(seq, half_window=10)
    assert p[0] == 0.0  # the only win is game 0 itself
    assert p[1] == 0.25
    assert np.allclose(q3.local_win_rate(seq, None), 0.2)


def test_block_permutations_keep_each_block_s_results():
    rng = np.random.default_rng(0)
    seq = np.array([1] * 5 + [0] * 5 + [1, 0] * 5)
    sims = q3.block_permutations(seq, rng, n_sims=50, block_size=10)
    assert (sims[:, :10].sum(axis=1) == 5).all()
    assert (sims[:, 10:].sum(axis=1) == 5).all()


def test_h3_block_null_is_calibrated_for_independent_games():
    res = q3.fit_h3(simulate_sequences(300, 120, 0.0, seed=1), n_sims=1000, n_boot=2000)
    assert res.ci_low < 0 < res.ci_high
    assert abs(res.mean_z) < 0.15
    assert res.share_streaky < 0.06


def test_h3_detects_streaky_play():
    res = q3.fit_h3(simulate_sequences(300, 120, 0.05, seed=2), n_sims=1000, n_boot=2000)
    assert res.ci_high < -0.5


def test_registered_drift_null_rejects_independent_games():
    """Why Deviation 2 exists: the registered null calls independent play anti-streaky."""
    res = q3.fit_h3(
        simulate_sequences(300, 120, 0.0, seed=1), n_sims=1000, n_boot=2000, null="drift"
    )
    assert res.ci_low > 0.2
