from ekko_analysis import q2
from ekko_analysis.simulate import simulate_team_strength


def test_h2_recovers_planted_delta():
    res = q2.fit_h2(simulate_team_strength(delta=-60, seed=1))
    assert abs(res.delta.estimate + 60) < 3 * res.delta.se
    assert not res.equivalent


def test_h2_equivalence_when_no_loser_s_queue():
    res = q2.fit_h2(simulate_team_strength(delta=0, seed=2))
    assert res.equivalent
    assert res.tost_p_value < 0.05
    assert res.delta_90.ci_high - res.delta_90.ci_low < res.delta.ci_high - res.delta.ci_low


def test_h2a_detects_autofill_imbalance():
    assert q2.fit_h2a(simulate_team_strength(autofill_effect=0.3, seed=3)).p_value < 0.01
