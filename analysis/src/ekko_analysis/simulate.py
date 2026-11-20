"""Simulated data with known effects, shaped like the dbt marts, for validating every model.

`simulate_player_games` generates focal-player histories: sessions and breaks, a latent performance
that drives both the standardized outcome and the win, and optional planted effects:

- beta: tilt, the effect of losing the previous same-session game on performance
- beta_by_tier: a different beta per tier group (H1c)
- gamma: persistence of performance from one game to the next (the "bad day" path that the
  lagged-performance control exists for)
- session_form_sd: a per-session form shock shared by every game in a session (a confounder the
  registered model does not fully absorb; used to measure its bias, not assumed away)
- p_continue_after_win / _loss: selective continuation (section 5.1)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TIER_OF_GROUP = {"iron_silver": "SILVER", "gold_platinum": "GOLD", "emerald_plus": "DIAMOND"}
ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def _break_bucket(minutes: float) -> str | None:
    if np.isnan(minutes):
        return None
    for limit, label in [(15, "lt_15m"), (60, "15_60m"), (360, "1_6h"), (1440, "6_24h")]:
        if minutes < limit:
            return label
    return "gt_24h"


def simulate_player_games(
    n_players: int = 300,
    games_per_player: int = 80,
    beta: float = 0.0,
    gamma: float = 0.2,
    beta_by_tier: dict[str, float] | None = None,
    session_form_sd: float = 0.0,
    p_continue_after_win: float = 0.6,
    p_continue_after_loss: float = 0.6,
    short_game_rate: float = 0.05,
    seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    groups = list(TIER_OF_GROUP)
    rows = []
    for i in range(n_players):
        alpha = rng.normal(0, 0.3)
        tier_group = groups[i % len(groups)]
        b = beta_by_tier[tier_group] if beta_by_tier else beta
        clock = rng.uniform(0, 1e5)
        prev = None  # (perf, lost, z, session_loss_run)
        form = 0.0
        game_in_session = 0
        for t in range(games_per_player):
            if prev is None:
                brk = float("nan")
                new_session = True
            else:
                p_cont = p_continue_after_loss if prev[1] else p_continue_after_win
                brk = rng.uniform(1, 59) if rng.random() < p_cont else rng.uniform(60, 3000)
                new_session = brk >= 60
                clock += brk
            if new_session:
                form = rng.normal(0, session_form_sd) if session_form_sd else 0.0
                game_in_session = 1
                lost_prev = None
                loss_run = None
            else:
                game_in_session += 1
                lost_prev = prev[1]
                loss_run = (prev[3] + 1) if prev[1] else 0
            perf = (
                alpha
                + form
                + (b if lost_prev else 0.0)
                + (gamma * prev[0] if prev is not None else 0.0)
                + rng.normal()
            )
            win = rng.random() < 1 / (1 + np.exp(-1.2 * (perf - alpha)))
            short = rng.random() < short_game_rate
            z = float("nan") if short else perf

            rows.append(
                {
                    "player_key": f"p{i:05d}",
                    "match_key": f"m{i:05d}_{t:04d}",
                    "game_start_at": clock,
                    "champion_key": int(rng.integers(0, 40)),
                    "role_key": ROLES[int(rng.integers(0, 5))],
                    "patch": f"16.{int(rng.integers(1, 4))}",
                    "hour_local": int(rng.integers(0, 24)),
                    "iso_day_of_week": int(rng.integers(1, 8)),
                    "sampled_tier": TIER_OF_GROUP[tier_group],
                    "tier_group": tier_group,
                    "remake": False,
                    "win": bool(win),
                    "gold_diff_14_z": z,
                    "cs_diff_14_z": z + rng.normal(0, 0.5) if not short else float("nan"),
                    "xp_diff_14_z": z + rng.normal(0, 0.5) if not short else float("nan"),
                    "deaths_before_14_z": -z + rng.normal(0, 0.8) if not short else float("nan"),
                    "perf_index": z + rng.normal(0, 0.3) if not short else float("nan"),
                    "prev_gold_diff_14_z": prev[2] if prev is not None else float("nan"),
                    "prev_game_won": (not prev[1]) if prev is not None else None,
                    "minutes_since_last_game": brk,
                    "break_bucket": _break_bucket(brk),
                    "game_number_in_session": game_in_session,
                    "lost_prev": lost_prev,
                    "session_loss_run": None
                    if loss_run is None
                    else ("3+" if loss_run >= 3 else str(loss_run)),
                    "outcome_eligible": not short,
                    "duration_seconds": 600 if short else int(rng.uniform(900, 2400)),
                    "likely_duo": bool(rng.random() < 0.1),
                }
            )
            clock += 30
            prev = (perf, not win, z, loss_run if loss_run is not None else 0)
    df = pd.DataFrame(rows)
    df["lost_prev"] = df["lost_prev"].astype("boolean")
    df["prev_game_won"] = df["prev_game_won"].astype("boolean")
    df["q1_eligible"] = (
        df["outcome_eligible"] & df["lost_prev"].notna() & df["gold_diff_14_z"].notna()
    )
    return df


def simulate_sequences(
    n_players: int = 500, n_games: int = 120, stickiness: float = 0.0, seed: int = 0
) -> dict[str, np.ndarray]:
    """Win/loss sequences. stickiness = P(repeat last result) - 0.5; 0 means independent games."""
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n_players):
        seq = np.empty(n_games, dtype=int)
        seq[0] = rng.random() < 0.5
        for t in range(1, n_games):
            seq[t] = seq[t - 1] if rng.random() < 0.5 + stickiness else 1 - seq[t - 1]
        out[f"p{i:05d}"] = seq
    return out


def simulate_team_strength(
    n_matches: int = 10_000,
    n_players: int = 2_000,
    delta: float = 0.0,
    autofill_effect: float = 0.0,
    gap_sd: float = 150.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Q2 matches. delta is the planted W3+ minus L3+ difference in strength gap (LP)."""
    rng = np.random.default_rng(seed)
    states = np.array(["L3+", "L2", "streak_1", "W2", "W3+"])
    state = rng.choice(states, size=n_matches, p=[0.12, 0.13, 0.5, 0.13, 0.12])
    ladder = rng.uniform(0, 3200, n_matches)
    shift = np.select([state == "W3+", state == "L3+"], [delta / 2, -delta / 2], 0.0)
    af_shift = np.select([state == "W3+", state == "L3+"], [autofill_effect, -autofill_effect], 0.0)
    gap = 20 * np.sin(ladder / 800) + shift + rng.normal(0, gap_sd, n_matches)
    won = rng.random(n_matches) < 1 / (1 + np.exp(-gap / 200))
    return pd.DataFrame(
        {
            "player_key": rng.integers(0, n_players, n_matches).astype(str),
            "streak_state": state,
            "focal_ladder_position": ladder,
            "strength_gap": gap,
            "strength_gap_unadjusted": gap + np.where(won, 40.0, -40.0),
            "won_match": won,
            "autofill_sample": rng.random(n_matches) < 0.3,
            "autofill_gap": np.round(af_shift + rng.normal(0, 1, n_matches)),
            "hour_local": rng.integers(0, 24, n_matches),
            "iso_day_of_week": rng.integers(1, 8, n_matches),
            "patch": rng.choice(["16.1", "16.2", "16.3"], n_matches),
            "sampled_tier": rng.choice(list(TIER_OF_GROUP.values()), n_matches),
        }
    )
