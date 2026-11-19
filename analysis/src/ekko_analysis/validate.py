"""Validate the models on real data structure with shuffled outcomes (PREREGISTRATION.md 9).

Uses the real sessions, breaks, champions, patches and players from the warehouse, but shuffles each
player's outcomes, which breaks any link between outcomes and exposures. Then plants a known
effect and checks that the model recovers it and holds its false-positive rate. No real
outcome-exposure relationship is computed.

    python -m ekko_analysis.validate [--reps 200]
"""

from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

from . import q1, q3, selection
from .data import load_player_games


def _ordered(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["player_key", "game_start_at", "match_key"])


def shuffled_with_planted_tilt(
    df: pd.DataFrame, beta: float, rng: np.random.Generator
) -> pd.DataFrame:
    """Shuffle gold_diff_14_z within player (missing positions stay missing), add beta after a
    same-session loss, and rebuild the lagged outcome from the new values."""
    d = _ordered(df.loc[~df["remake"].astype(bool)]).copy()
    z = d["gold_diff_14_z"].to_numpy(copy=True)
    for idx in d.groupby("player_key").indices.values():
        present = idx[~np.isnan(z[idx])]
        z[present] = rng.permutation(z[present])
    z = z + beta * d["lost_prev"].fillna(False).astype(bool).to_numpy()
    d["gold_diff_14_z"] = z
    d["prev_gold_diff_14_z"] = d.groupby("player_key")["gold_diff_14_z"].shift(1)
    return d


def shuffled_wins(df: pd.DataFrame, rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {k: rng.permutation(v) for k, v in q3.win_sequences(df).items()}


def _summary(estimates, truth) -> dict:
    est = pd.DataFrame([e.__dict__ for e in estimates])
    return {
        "true": truth,
        "mean estimate": est.estimate.mean(),
        "bias": est.estimate.mean() - truth,
        "reject (p<.05)": (est.p_value < 0.05).mean(),
        "95% CI coverage": ((est.ci_low <= truth) & (truth <= est.ci_high)).mean(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args(argv)
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(args.seed)

    df = load_player_games()
    print(
        f"Warehouse: {df.player_key.nunique()} players, {len(df)} player-games, "
        f"{int(df.q1_eligible.sum())} in the H1 sample. Outcomes are shuffled in every replicate.\n"
    )

    rows = []
    for beta in (0.0, -0.2):
        for lag in ("drop", "fill"):
            ests = [
                q1.fit_h1(shuffled_with_planted_tilt(df, beta, rng), lag=lag)
                for _ in range(args.reps)
            ]
            rows.append({"model": f"H1 lag={lag}", **_summary(ests, beta)})

    shuffled_results = []
    for _ in range(args.reps):
        d = _ordered(df.loc[~df["remake"].astype(bool)]).copy()
        d["win"] = d.groupby("player_key")["win"].transform(lambda s: rng.permutation(s.to_numpy()))
        shuffled_results.append(selection.fit_continuation(d).loss_effect)
    rows.append({"model": "continuation (shuffled wins)", **_summary(shuffled_results, 0.0)})
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    print("\nH3 on shuffled win sequences (independent by construction; mean z should be ~0):")
    for null in ("block", "drift"):
        res = q3.fit_h3(shuffled_wins(df, rng), n_sims=2000, n_boot=2000, null=null)
        print(
            f"  null={null:5s} mean z {res.mean_z:+.3f}"
            f"  95% CI [{res.ci_low:+.3f}, {res.ci_high:+.3f}]  players {res.n_players}"
        )


if __name__ == "__main__":
    main()
