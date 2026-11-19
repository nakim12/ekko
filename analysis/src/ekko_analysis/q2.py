"""Q2, loser's queue (PREREGISTRATION.md section 7).

Input: one row per Q2 match, shaped like the planned mart `fct_match_team_strength`:
strength_gap (LP), streak_state, focal_ladder_position, hour_local, iso_day_of_week, patch,
sampled_tier, player_key; plus autofill_gap for H2a.

    strength_gap = sum_s d_s * streak_state_s (baseline streak_1) + spline(focal ladder, 4 df)
                   | hour + day of week + patch + sampled tier

H2 is an equivalence claim: Delta = d(W3+) - d(L3+) lies within +-25 LP (TOST, 90% CI).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pyfixest as pf
from scipy import stats

from .inference import Estimate, WaldTest, joint_wald, linear_contrast

EQUIVALENCE_BOUND_LP = 25.0
STATES = ["L3+", "L2", "W2", "W3+"]  # baseline: streak_1
FIXED_EFFECTS = ["hour_local", "iso_day_of_week", "patch", "sampled_tier"]


@dataclass(frozen=True)
class H2Result:
    delta: Estimate  # W3+ minus L3+, 95% CI
    delta_90: Estimate  # same contrast, 90% CI (for TOST)
    tost_p_value: float
    equivalent: bool  # 90% CI inside +-bound
    bound: float
    states: dict[str, Estimate]


def _prepare(df: pd.DataFrame, outcome: str) -> pd.DataFrame:
    d = df.loc[df[outcome].notna() & df["streak_state"].notna()].copy()
    d["y"] = d[outcome].astype(float)
    for s in STATES:
        d[_col(s)] = (d["streak_state"] == s).astype(int)
    for col in FIXED_EFFECTS + ["player_key"]:
        d[col] = d[col].astype(str)
    return d


def _col(state: str) -> str:
    return "state_" + state.replace("+", "p")


def _fit(d: pd.DataFrame):
    rhs = " + ".join(_col(s) for s in STATES) + " + bs(focal_ladder_position, df=4)"
    return pf.feols(f"y ~ {rhs} | {' + '.join(FIXED_EFFECTS)}", data=d, vcov={"CRV1": "player_key"})


def fit_h2(df: pd.DataFrame, outcome: str = "strength_gap", bound: float = EQUIVALENCE_BOUND_LP) -> H2Result:
    d = _prepare(df, outcome)
    fit = _fit(d)
    kw = dict(n_obs=len(d), n_clusters=d.player_key.nunique())
    w = {_col("W3+"): 1.0, _col("L3+"): -1.0}
    delta = linear_contrast(fit, w, name="H2 delta (W3+ - L3+)", **kw)
    delta_90 = linear_contrast(fit, w, name="H2 delta (90% CI)", level=0.90, **kw)
    dof = max(delta.n_clusters - 1, 1)
    p_lower = stats.t.sf((delta.estimate + bound) / delta.se, dof)  # H0: delta <= -bound
    p_upper = stats.t.cdf((delta.estimate - bound) / delta.se, dof)  # H0: delta >= +bound
    states = {s: linear_contrast(fit, {_col(s): 1.0}, name=f"H2 {s}", **kw) for s in STATES}
    return H2Result(
        delta,
        delta_90,
        float(max(p_lower, p_upper)),
        bool(-bound < delta_90.ci_low and delta_90.ci_high < bound),
        bound,
        states,
    )


def fit_h2a(df: pd.DataFrame, outcome: str = "autofill_gap") -> WaldTest:
    """H2a: are all streak-state effects on the autofill gap zero?"""
    d = _prepare(df, outcome)
    fit = _fit(d)
    return joint_wald(fit, [_col(s) for s in STATES], n_clusters=d.player_key.nunique())
