"""Personal report statistics (PROJECT_PLAN.md 8.1-8.2).

- tilt: the player's own H1 regression (standardized gold diff at 14 on losing the previous
  same-session game, controlling for the previous game's score and the break), then empirical
  Bayes shrinkage toward their tier's average: precision-weighted, so noisy players are pulled
  harder.
- cooldown: the same loss effect after a quick requeue (< 15 min) and after a longer break
  (15 min to 6 h, any session).
- stop rule: win rate after 2+ losses in a row within a session, with a Wilson interval; only
  "supported" when the whole interval is below the player's usual win rate.
- matchmaking: mean strength gap (teammates minus enemies, LP) over the last 10 games.

Every block carries `supported`, which the AI coach must respect: no claim without support.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats as st

from .features import Game, log_break

MIN_TILT_GAMES = 15
MIN_GROUP_GAMES = 5
STOP_AFTER_LOSSES = 2


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float
    n: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


def _ols_loss_effect(rows: list[Game]) -> tuple[float, float, int] | None:
    """Coefficient on 'lost the previous game' with an HC1 standard error, or None if too few."""
    rows = [g for g in rows if g.z is not None and g.prev_z is not None and g.prev_won is not None]
    lost = np.array([0.0 if g.prev_won else 1.0 for g in rows])
    if (
        len(rows) < MIN_TILT_GAMES
        or lost.sum() < MIN_GROUP_GAMES
        or (1 - lost).sum() < MIN_GROUP_GAMES
    ):
        return None
    x = np.column_stack(
        [np.ones(len(rows)), lost, [g.prev_z for g in rows], [log_break(g) for g in rows]]
    )
    y = np.array([g.z for g in rows])
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    n, k = x.shape
    meat = (x * resid[:, None] ** 2).T @ x
    cov = xtx_inv @ meat @ xtx_inv * n / max(n - k, 1)
    return float(beta[1]), float(math.sqrt(max(cov[1, 1], 0.0))), n


def _interval(est: float, se: float, n: int) -> Interval:
    return Interval(est, est - 1.96 * se, est + 1.96 * se, n)


def shrink(est: float, se: float, prior_mean: float, prior_sd: float) -> tuple[float, float]:
    """Normal-normal posterior: precision-weighted mix of the player's estimate and the prior."""
    w_data, w_prior = 1 / se**2, 1 / prior_sd**2
    mean = (w_data * est + w_prior * prior_mean) / (w_data + w_prior)
    return mean, math.sqrt(1 / (w_data + w_prior))


def tilt(games: list[Game], prior: dict, gold_sd: float) -> dict:
    same_session = [g for g in games if g.lost_prev is not None]
    fit = _ols_loss_effect(same_session)
    out = {
        "games_used": 0,
        "tier_average": prior["mean"],
        "prior_is_placeholder": prior.get("placeholder", False),
        "raw": None,
        "shrunk": None,
        "gold_equivalent": None,
        "supported": False,
    }
    if fit is None:
        return {**out, "reason": "not enough same-session games after both wins and losses"}
    est, se, n = fit
    post_mean, post_sd = shrink(est, se, prior["mean"], prior["sd"])
    shrunk = _interval(post_mean, post_sd, n)
    return {
        **out,
        "games_used": n,
        "raw": asdict(_interval(est, se, n)),
        "shrunk": asdict(shrunk),
        "gold_equivalent": round(post_mean * gold_sd),
        "supported": shrunk.excludes_zero,
        "direction": "worse after a loss" if post_mean < 0 else "better after a loss",
    }


def cooldown(games: list[Game]) -> dict:
    quick = [g for g in games if g.break_minutes is not None and g.break_minutes < 15]
    slow = [g for g in games if g.break_minutes is not None and 15 <= g.break_minutes < 360]
    out = {}
    for name, rows in (("quick_requeue", quick), ("after_a_break", slow)):
        fit = _ols_loss_effect(rows)
        out[name] = asdict(_interval(*fit)) if fit else None
    q, s = out["quick_requeue"], out["after_a_break"]
    # Supported only if a quick requeue shows a drop and a break clearly doesn't.
    out["supported"] = bool(q and s and q["high"] < 0 and s["low"] <= 0 <= s["high"])
    return out


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return center - half, center + half


def stop_rule(games: list[Game], after: int = STOP_AFTER_LOSSES) -> dict:
    after_streak = [g for g in games if (g.session_losses_before or 0) >= after]
    wins = sum(g.win for g in after_streak)
    overall = sum(g.win for g in games) / len(games) if games else float("nan")
    low, high = wilson(wins, len(after_streak))
    return {
        "after_losses_in_a_row": after,
        "games": len(after_streak),
        "win_rate": wins / len(after_streak) if after_streak else None,
        "low": low,
        "high": high,
        "overall_win_rate": overall,
        "supported": bool(after_streak) and len(after_streak) >= 10 and high < overall,
    }


def matchmaking(gaps: list[float]) -> dict:
    """gaps: teammates' minus enemies' mean ladder position (LP) for each of the last games."""
    gaps = [g for g in gaps if g is not None and not math.isnan(g)]
    out = {
        "games": len(gaps),
        "caveat": "One player's recent games can't show whether matchmaking is fair; the study "
        "answers that across thousands of matches.",
        "supported": False,  # never a claim about the matchmaker from one player
    }
    if len(gaps) < 3:
        return {**out, "mean_gap_lp": None, "low": None, "high": None}
    mean, sd = float(np.mean(gaps)), float(np.std(gaps, ddof=1))
    half = st.t.ppf(0.975, len(gaps) - 1) * sd / math.sqrt(len(gaps))
    return {**out, "mean_gap_lp": mean, "low": mean - half, "high": mean + half}
