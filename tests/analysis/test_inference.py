import numpy as np
import pandas as pd
import pyfixest as pf
import pytest
from ekko_analysis.inference import benjamini_hochberg, holm, joint_wald, linear_contrast


@pytest.fixture
def fit_and_data():
    rng = np.random.default_rng(0)
    n = 4000
    d = pd.DataFrame(
        {"g": rng.integers(0, 200, n).astype(str), "a": rng.normal(size=n), "b": rng.normal(size=n)}
    )
    d["y"] = 0.5 * d.a - 0.2 * d.b + rng.normal(size=n)
    return pf.feols("y ~ a + b | g", data=d, vcov={"CRV1": "g"}), d


def test_contrast_matches_coefficients(fit_and_data):
    fit, d = fit_and_data
    coef = fit.coef()
    est = linear_contrast(fit, {"a": 1, "b": -1}, name="a-b", n_obs=len(d), n_clusters=200)
    assert est.estimate == pytest.approx(coef["a"] - coef["b"])
    single = linear_contrast(fit, {"a": 1}, name="a", n_obs=len(d), n_clusters=200)
    assert single.se == pytest.approx(float(fit.se()["a"]))
    assert single.ci_low < 0.5 < single.ci_high


def test_contrast_rejects_unknown_coefficient(fit_and_data):
    fit, d = fit_and_data
    with pytest.raises(KeyError):
        linear_contrast(fit, {"nope": 1}, name="x", n_obs=len(d), n_clusters=200)


def test_wald_with_one_coefficient_is_t_squared(fit_and_data):
    fit, d = fit_and_data
    single = linear_contrast(fit, {"b": 1}, name="b", n_obs=len(d), n_clusters=200)
    w = joint_wald(fit, ["b"], n_clusters=200)
    assert w.f_stat == pytest.approx((single.estimate / single.se) ** 2)
    assert w.p_value == pytest.approx(single.p_value)


def test_multiplicity_corrections():
    reject, adj = holm([0.01, 0.04, 0.03])
    assert list(reject) == [True, False, False]
    assert adj[0] == pytest.approx(0.03)
    reject, adj = benjamini_hochberg([0.01, 0.02, 0.03, 0.5])
    assert list(reject) == [True, True, True, False]
    assert adj[2] == pytest.approx(0.04)
