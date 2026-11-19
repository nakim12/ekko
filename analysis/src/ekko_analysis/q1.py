"""Q1, tilt (PREREGISTRATION.md section 5): within-player fixed-effects models.

Input is a frame shaped like the dbt mart `fct_player_games` (see `data.load_player_games`).

    y[i,t] = b * lost_prev + g * prev_perf (+ missing-lag indicator) + log(break)
             | player + champion + role + patch + hour + game-number-in-session fixed effects

The lagged performance control is the previous game's standardized gold difference at 14 for
every outcome, since it stands for "how well you played last game".

Missing lag (Deviation 1 in PREREGISTRATION.md): when the previous game has no score (under 14
minutes, AFK, no lane opponent), the registered model sets the lag to 0 with an indicator.
Simulation showed that biases b toward "tilt" (the previous result stands in for the unmeasured
performance), so by default those rows are dropped (`lag="drop"`). `lag="fill"` reproduces the
registered model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyfixest as pf

from .inference import Estimate, WaldTest, joint_wald, linear_contrast

PRIMARY = "gold_diff_14_z"
SECONDARY = ["cs_diff_14_z", "xp_diff_14_z", "deaths_before_14_z", "perf_index", "win"]
FIXED_EFFECTS = ["player_key", "champion_key", "role_key", "patch", "hour_local", "game_num_bucket"]
CONTROLS = "prev_perf + prev_missing + log_break"
BREAK_BUCKETS = ["lt_15m", "15_60m", "1_6h", "6_24h"]
TIER_GROUPS = ["iron_silver", "gold_platinum", "emerald_plus"]


@dataclass(frozen=True)
class GroupedResult:
    """Per-group effects plus a joint test that they don't differ (H1a-c)."""

    effects: dict[str, Estimate]
    joint_test: WaldTest | None
    trend: Estimate | None = None


LAG_MODES = ("drop", "fill")


def prepare(df: pd.DataFrame, outcome: str, sample: pd.Series, lag: str = "drop") -> pd.DataFrame:
    """Rows in `sample` with the outcome present, plus model-ready controls."""
    if lag not in LAG_MODES:
        raise ValueError(f"lag must be one of {LAG_MODES}")
    keep = sample.fillna(False).astype(bool) & df[outcome].notna()
    if lag == "drop":
        keep &= df["prev_gold_diff_14_z"].notna()
    d = df.loc[keep].copy()
    d["y"] = d[outcome].astype(float)
    d["prev_perf"] = d["prev_gold_diff_14_z"].astype(float).fillna(0.0)
    d["prev_missing"] = d["prev_gold_diff_14_z"].isna().astype(int)
    d["log_break"] = np.log1p(d["minutes_since_last_game"].astype(float).clip(lower=0))
    d["game_num_bucket"] = d["game_number_in_session"].clip(upper=7).astype(int).astype(str)
    for col in FIXED_EFFECTS:
        d[col] = d[col].astype(str)
    return d


def _fit(d: pd.DataFrame, rhs: str, extra_fe: str = "", weights: str | None = None):
    fe = " + ".join(FIXED_EFFECTS) + (f" + {extra_fe}" if extra_fe else "")
    return pf.feols(f"y ~ {rhs} | {fe}", data=d, vcov={"CRV1": "player_key"}, weights=weights)


def _q1_sample(df: pd.DataFrame) -> pd.Series:
    return df["q1_eligible"].astype(bool)


def fit_h1(
    df: pd.DataFrame, outcome: str = PRIMARY, weights: str | None = None, lag: str = "drop"
) -> Estimate:
    """H1: effect of losing the previous same-session game. `weights` names a column (IPW)."""
    d = prepare(df, outcome, _q1_sample(df), lag)
    d["lost"] = d["lost_prev"].astype(int)
    fit = _fit(d, f"lost + {CONTROLS}", weights=weights)
    return linear_contrast(
        fit, {"lost": 1.0}, name=f"H1 {outcome}", n_obs=len(d), n_clusters=d.player_key.nunique()
    )


def fit_h1a(df: pd.DataFrame, outcome: str = PRIMARY, lag: str = "drop") -> GroupedResult:
    """H1a: effect by consecutive in-session losses (1, 2, 3+; 0 = previous game won).

    The trend test is the linear contrast across the three equally spaced categories (3+ minus 1).
    """
    d = prepare(df, outcome, _q1_sample(df), lag)
    for label, col in [("1", "loss_1"), ("2", "loss_2"), ("3+", "loss_3p")]:
        d[col] = (d["session_loss_run"] == label).astype(int)
    fit = _fit(d, f"loss_1 + loss_2 + loss_3p + {CONTROLS}")
    kw = dict(n_obs=len(d), n_clusters=d.player_key.nunique())
    effects = {
        k: linear_contrast(fit, {c: 1.0}, name=f"H1a losses={k}", **kw)
        for k, c in [("1", "loss_1"), ("2", "loss_2"), ("3+", "loss_3p")]
    }
    trend = linear_contrast(fit, {"loss_3p": 1.0, "loss_1": -1.0}, name="H1a trend", **kw)
    return GroupedResult(effects, None, trend)


def fit_h1b(df: pd.DataFrame, outcome: str = PRIMARY, lag: str = "drop") -> GroupedResult:
    """H1b: does the loss effect change with the break? Sample: previous game ended within 24 h."""
    sample = (
        df["outcome_eligible"].astype(bool)
        & df["prev_game_won"].notna()
        & df["break_bucket"].isin(BREAK_BUCKETS)
    )
    d = prepare(df, outcome, sample, lag)
    d["lost"] = (~d["prev_game_won"].astype(bool)).astype(int)
    inter = {b: f"lost_x_{i}" for i, b in enumerate(BREAK_BUCKETS) if i > 0}
    for b, col in inter.items():
        d[col] = d["lost"] * (d["break_bucket"] == b).astype(int)
    fit = _fit(d, f"lost + {' + '.join(inter.values())} + {CONTROLS}", extra_fe="break_bucket")
    kw = dict(n_obs=len(d), n_clusters=d.player_key.nunique())
    effects = {BREAK_BUCKETS[0]: linear_contrast(fit, {"lost": 1.0}, name="H1b lt_15m", **kw)}
    for b, col in inter.items():
        effects[b] = linear_contrast(fit, {"lost": 1.0, col: 1.0}, name=f"H1b {b}", **kw)
    test = joint_wald(fit, list(inter.values()), n_clusters=d.player_key.nunique())
    return GroupedResult(effects, test)


def fit_h1c(df: pd.DataFrame, outcome: str = PRIMARY, lag: str = "drop") -> GroupedResult:
    """H1c: does the loss effect differ across tier groups? (Tier main effects are absorbed by
    the player fixed effect, since sampled tier is fixed per player.)"""
    d = prepare(df, outcome, _q1_sample(df), lag)
    d["lost"] = d["lost_prev"].astype(int)
    inter = {g: f"lost_x_{g}" for g in TIER_GROUPS[1:]}
    for g, col in inter.items():
        d[col] = d["lost"] * (d["tier_group"] == g).astype(int)
    fit = _fit(d, f"lost + {' + '.join(inter.values())} + {CONTROLS}")
    kw = dict(n_obs=len(d), n_clusters=d.player_key.nunique())
    effects = {TIER_GROUPS[0]: linear_contrast(fit, {"lost": 1.0}, name="H1c iron_silver", **kw)}
    for g, col in inter.items():
        effects[g] = linear_contrast(fit, {"lost": 1.0, col: 1.0}, name=f"H1c {g}", **kw)
    test = joint_wald(fit, list(inter.values()), n_clusters=d.player_key.nunique())
    return GroupedResult(effects, test)
