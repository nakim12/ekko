"""Q1 selection (PREREGISTRATION.md 5.1): who keeps playing after a loss.

1. Continuation model: P(next game starts within the session gap) after a loss vs. a win.
2. Inverse probability weights for the H1 sample (each H1 game exists because the previous one
   was continued, so its weight is 1 / P(continue) of the previous game).
3. Pattern-mixture bound: how much better (or worse) players who stopped after a loss would have to
   play for the H1 interval to reach zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyfixest as pf
import statsmodels.formula.api as smf

from .inference import Estimate, linear_contrast

SESSION_GAP_MINUTES = 60


@dataclass(frozen=True)
class Continuation:
    """Continuation after a loss vs. a win (LPM with player FE) and the raw stop rates."""

    loss_effect: Estimate
    stop_rate_after_loss: float
    stop_rate_after_win: float


@dataclass(frozen=True)
class SelectionBound:
    """delta: the shift (in outcome SD) that players who stopped after a loss would need, relative
    to those who continued, for the H1 95% interval to reach zero. None if it already includes 0."""

    delta: float | None
    stop_rate_after_loss: float
    explanation: str


def ordered_games(df: pd.DataFrame) -> pd.DataFrame:
    """Non-remake focal games in time order per player."""
    g = df.loc[~df["remake"].astype(bool)].copy()
    return g.sort_values(["player_key", "game_start_at", "match_key"])


def continuation_frame(df: pd.DataFrame, gap: float = SESSION_GAP_MINUTES) -> pd.DataFrame:
    """One row per game with a known next step: did another game start within `gap` minutes?

    Each player's last crawled game is dropped (what happened next is unknown).
    """
    g = ordered_games(df)
    next_break = g.groupby("player_key")["minutes_since_last_game"].shift(-1)
    g = g.loc[next_break.notna()].copy()
    g["continued"] = (next_break.loc[g.index] < gap).astype(int)
    g["lost"] = (~g["win"].astype(bool)).astype(int)
    g["own_perf"] = g["gold_diff_14_z"].astype(float).fillna(0.0)
    g["own_missing"] = g["gold_diff_14_z"].isna().astype(int)
    g["game_num_bucket"] = g["game_number_in_session"].clip(upper=7).astype(int).astype(str)
    for col in ["player_key", "hour_local", "iso_day_of_week"]:
        g[col] = g[col].astype(str)
    return g


def fit_continuation(df: pd.DataFrame, gap: float = SESSION_GAP_MINUTES) -> Continuation:
    """5.1.1: linear probability of continuing, losses vs. wins, within player."""
    c = continuation_frame(df, gap)
    fit = pf.feols(
        "continued ~ lost + own_perf + own_missing"
        " | player_key + game_num_bucket + hour_local + iso_day_of_week",
        data=c,
        vcov={"CRV1": "player_key"},
    )
    est = linear_contrast(
        fit,
        {"lost": 1.0},
        name="continuation after loss vs. win",
        n_obs=len(c),
        n_clusters=c.player_key.nunique(),
    )
    return Continuation(
        est,
        stop_rate_after_loss=float(1 - c.loc[c.lost == 1, "continued"].mean()),
        stop_rate_after_win=float(1 - c.loc[c.lost == 0, "continued"].mean()),
    )


def ipw_weights(
    df: pd.DataFrame, gap: float = SESSION_GAP_MINUTES, trim: float = 0.01
) -> pd.Series:
    """5.1.2: weights for every game, indexed like `df`: 1 / P(previous game was continued).

    P comes from a logistic model with the player's leave-one-out continuation rate standing in
    for the player fixed effect. Weights are trimmed at the `trim` and 1 - `trim` quantiles of the
    H1 sample. Games without a modeled previous game get NaN.
    """
    c = continuation_frame(df, gap)
    by_player = c.groupby("player_key")["continued"]
    total, count = by_player.transform("sum"), by_player.transform("count")
    overall = c["continued"].mean()
    c["player_rate"] = np.where(
        count > 1, (total - c["continued"]) / (count - 1).clip(lower=1), overall
    )
    model = smf.logit(
        "continued ~ lost + own_perf + own_missing + C(game_num_bucket) + C(hour_local)"
        " + C(iso_day_of_week) + player_rate",
        data=c,
    ).fit(disp=False)
    c["p_continue"] = model.predict(c).clip(1e-3, 1)

    g = ordered_games(df)
    g = g.join(c["p_continue"])
    prev_p = g.groupby("player_key")["p_continue"].shift(1)
    weights = (1 / prev_p).reindex(df.index)

    h1 = df["q1_eligible"].astype(bool) & weights.notna()
    lo, hi = weights[h1].quantile([trim, 1 - trim])
    return weights.clip(lo, hi)


def selection_bound(h1: Estimate, stop_rate_after_loss: float) -> SelectionBound:
    """5.1.3: pattern-mixture sensitivity.

    Suppose players who stopped after a loss would have played delta SD differently from those who
    continued (and stopping after a win is uninformative). The effect over all post-loss games is
    then b + s * delta, where s is the stop rate after a loss. Solve for the delta that moves the
    end of the 95% interval nearest zero onto zero.
    """
    s = stop_rate_after_loss
    if h1.ci_low <= 0 <= h1.ci_high:
        return SelectionBound(None, s, "The 95% interval already includes 0.")
    bound = h1.ci_high if h1.estimate < 0 else h1.ci_low
    delta = -bound / s
    direction = "better" if delta > 0 else "worse"
    return SelectionBound(
        float(delta),
        s,
        f"Players who stopped after a loss would need to play {abs(delta):.3f} SD {direction} "
        f"than those who continued for the interval to reach 0 (stop rate after loss {s:.1%}).",
    )
