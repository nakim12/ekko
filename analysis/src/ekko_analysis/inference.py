"""Inference helpers: estimates, linear contrasts, joint Wald tests, multiplicity corrections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests


@dataclass(frozen=True)
class Estimate:
    """A point estimate with a confidence interval. Inference uses t with (clusters - 1) df."""

    name: str
    estimate: float
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    n_obs: int
    n_clusters: int
    level: float = 0.95

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass(frozen=True)
class WaldTest:
    """Joint test that a set of coefficients are all zero (cluster-robust F)."""

    names: tuple[str, ...]
    f_stat: float
    df_num: int
    df_den: int
    p_value: float


def coef_and_vcov(fit) -> tuple[pd.Series, pd.DataFrame]:
    """Coefficients and their cluster-robust covariance from a pyfixest fit, labeled by name."""
    names = list(fit._coefnames)
    coef = pd.Series(np.asarray(fit.coef()), index=names)
    vcov = pd.DataFrame(np.asarray(fit._vcov), index=names, columns=names)
    return coef, vcov


def linear_contrast(
    fit,
    weights: Mapping[str, float],
    *,
    name: str,
    n_obs: int,
    n_clusters: int,
    level: float = 0.95,
) -> Estimate:
    """Estimate of sum(w_k * b_k) with a t interval on (n_clusters - 1) df."""
    coef, vcov = coef_and_vcov(fit)
    missing = [k for k in weights if k not in coef.index]
    if missing:
        raise KeyError(f"coefficients not in model (dropped as collinear?): {missing}")
    w = pd.Series(weights, dtype=float)
    est = float(w @ coef[w.index])
    se = float(np.sqrt(w @ vcov.loc[w.index, w.index] @ w))
    return _estimate(name, est, se, n_obs, n_clusters, level)


def _estimate(name: str, est: float, se: float, n_obs: int, n_clusters: int, level: float):
    dof = max(n_clusters - 1, 1)
    crit = stats.t.ppf(0.5 + level / 2, dof)
    p = 2 * stats.t.sf(abs(est / se), dof) if se > 0 else float("nan")
    return Estimate(
        name, est, se, est - crit * se, est + crit * se, float(p), n_obs, n_clusters, level
    )


def joint_wald(fit, names: Sequence[str], *, n_clusters: int) -> WaldTest:
    """Cluster-robust F test that every coefficient in `names` is zero."""
    coef, vcov = coef_and_vcov(fit)
    b = coef[list(names)].to_numpy()
    v = vcov.loc[list(names), list(names)].to_numpy()
    q = len(names)
    f_stat = float(b @ np.linalg.solve(v, b) / q)
    df_den = max(n_clusters - 1, 1)
    return WaldTest(tuple(names), f_stat, q, df_den, float(stats.f.sf(f_stat, q, df_den)))


def holm(p_values: Sequence[float], alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Holm correction (primary family H1, H2, H3). Returns (reject, adjusted p)."""
    reject, adjusted, _, _ = multipletests(p_values, alpha=alpha, method="holm")
    return reject, adjusted


def benjamini_hochberg(p_values: Sequence[float], q: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg correction (secondary family). Returns (reject, adjusted p)."""
    reject, adjusted, _, _ = multipletests(p_values, alpha=q, method="fdr_bh")
    return reject, adjusted
