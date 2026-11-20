"""Q3, streak structure (PREREGISTRATION.md section 6): runs test per player.

For each player, the number of runs in their win/loss sequence is compared with 10,000 null
sequences. Fewer runs than the null means streakier; z < 0 is the streaky direction.

Null (Deviation 2 in PREREGISTRATION.md):
- "block" (default): the player's own results shuffled within consecutive blocks of 20 games. This
  keeps slow skill drift between blocks and is exactly calibrated when games are independent.
- "drift" (registered): Bernoulli draws with p_t = win rate over the 20 surrounding games.
  Simulation showed this null is streakier than independent play (it estimates drift from the
  same noisy games), so independent sequences score z ~ +0.5 and H3 would be rejected when true.
Registered sensitivities map to block_size=None (whole-sequence shuffle, i.e. a constant win rate)
and block_size=50.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

N_SIMULATIONS = 10_000
HALF_WINDOW = 10


@dataclass(frozen=True)
class PlayerRuns:
    observed_runs: int
    expected_runs: float
    z: float
    p_value: float  # two-sided simulation p


@dataclass(frozen=True)
class H3Result:
    mean_z: float
    ci_low: float
    ci_high: float
    n_players: int
    share_streaky: float  # players with p < .05 and z < 0; chance level is 2.5%
    p_value: float  # two-sided bootstrap p for mean z = 0 (for the Holm family)
    per_player: pd.DataFrame


def count_runs(seq: np.ndarray) -> np.ndarray:
    """Number of runs along the last axis of a 0/1 array."""
    seq = np.asarray(seq)
    return 1 + (np.diff(seq, axis=-1) != 0).sum(axis=-1)


def local_win_rate(seq: np.ndarray, half_window: int | None = HALF_WINDOW) -> np.ndarray:
    """p_t for the null: mean of up to `half_window` games on each side, excluding game t.

    `half_window=None` gives a constant rate (the player's overall rate), a registered sensitivity.
    """
    seq = np.asarray(seq, dtype=float)
    n = len(seq)
    if half_window is None:
        return np.full(n, seq.mean())
    csum = np.concatenate([[0.0], np.cumsum(seq)])
    idx = np.arange(n)
    lo = np.clip(idx - half_window, 0, n)
    hi = np.clip(idx + half_window + 1, 0, n)
    total = csum[hi] - csum[lo] - seq
    count = hi - lo - 1
    return np.where(count > 0, total / np.maximum(count, 1), seq.mean())


NULLS = ("block", "drift")
BLOCK_SIZE = 20


def block_permutations(
    seq: np.ndarray, rng: np.random.Generator, n_sims: int, block_size: int | None
):
    """n_sims copies of seq, each shuffled within consecutive blocks (None: the whole sequence)."""
    n = len(seq)
    block_id = np.arange(n) // (block_size or n)
    order = np.argsort(rng.random((n_sims, n)) + block_id, axis=1)
    return seq[order]


def player_runs_test(
    seq: np.ndarray,
    rng: np.random.Generator,
    n_sims: int = N_SIMULATIONS,
    null: str = "block",
    block_size: int | None = BLOCK_SIZE,
    half_window: int | None = HALF_WINDOW,
) -> PlayerRuns | None:
    """Runs test for one sequence; None when the null has no variance (e.g. all wins)."""
    if null not in NULLS:
        raise ValueError(f"null must be one of {NULLS}")
    seq = np.asarray(seq, dtype=int)
    if len(seq) < 2:
        return None
    if null == "block":
        sims = block_permutations(seq, rng, n_sims, block_size)
    else:
        p = local_win_rate(seq, half_window)
        sims = (rng.random((n_sims, len(seq))) < p).astype(np.int8)
    null_runs = count_runs(sims)
    sd = null_runs.std(ddof=1)
    if sd == 0:
        return None
    obs = int(count_runs(seq))
    lower = (np.sum(null_runs <= obs) + 1) / (n_sims + 1)
    upper = (np.sum(null_runs >= obs) + 1) / (n_sims + 1)
    z = (obs - null_runs.mean()) / sd
    return PlayerRuns(obs, float(null_runs.mean()), float(z), min(1.0, 2 * min(lower, upper)))


def win_sequences(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Each player's full win/loss sequence in time order, remakes removed."""
    g = df.loc[~df["remake"].astype(bool)].sort_values(["player_key", "game_start_at", "match_key"])
    return {k: v["win"].astype(int).to_numpy() for k, v in g.groupby("player_key", sort=True)}


def fit_h3(
    sequences: dict[str, np.ndarray],
    seed: int = 20261118,
    n_sims: int = N_SIMULATIONS,
    null: str = "block",
    block_size: int | None = BLOCK_SIZE,
    half_window: int | None = HALF_WINDOW,
    n_boot: int = 10_000,
) -> H3Result:
    """H3: mean per-player z with a bootstrap-over-players 95% CI."""
    rng = np.random.default_rng(seed)
    rows = []
    for key, seq in sequences.items():
        r = player_runs_test(seq, rng, n_sims, null, block_size, half_window)
        if r is not None:
            rows.append({"player_key": key, "n_games": len(seq), **r.__dict__})
    per_player = pd.DataFrame(rows)
    z = per_player["z"].to_numpy()
    boot = rng.choice(z, size=(n_boot, len(z)), replace=True).mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    streaky = ((per_player["p_value"] < 0.05) & (per_player["z"] < 0)).mean()
    p = min(1.0, 2 * min(float(np.mean(boot <= 0)), float(np.mean(boot >= 0))))
    return H3Result(float(z.mean()), float(lo), float(hi), len(z), float(streaky), p, per_player)
