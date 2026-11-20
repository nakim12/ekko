"""Every registered result from the Phase 1 warehouse, in one command (PREREGISTRATION.md).

    python -m ekko_analysis.run [--out analysis/results] [--session-warehouse 30=path ...]

Writes results.json (every estimate), results.md (the write-up tables), h3_per_player.csv and
h1_by_group.png to --out.

- Primary family (Holm): H1, H2 (equivalence), H3.
- Secondary family (BH): H1a trend, H1b, H1c, H2a, H1 on each secondary outcome, and continuation.
- Deviations 1 and 2 are applied, and the registered versions are reported next to them.
- Sensitivity runs from section 8. The session-threshold runs need dbt builds with
  session_gap_minutes 30, 90 and 120, passed as --session-warehouse 30=path/to/build.duckdb.

It refuses to run on anything but a full Phase 1 build (the Q2 mart exists and at least
MIN_PLAYERS focal players), so it can't be pointed at Phase 0 by accident. --allow-small lifts
that for demos, and only with an --out outside analysis/results.
"""

from __future__ import annotations

import argparse
import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import q1, q2, q3, selection
from .data import REPO_ROOT, load_player_games, load_team_strength, warehouse_path
from .inference import Estimate, benjamini_hochberg, holm

MIN_PLAYERS = 1_000
DEFAULT_OUT = REPO_ROOT / "analysis" / "results"


@dataclass
class Inputs:
    player_games: pd.DataFrame
    team_focal: pd.DataFrame
    team_placebo: pd.DataFrame
    session_variants: dict[int, pd.DataFrame] = field(default_factory=dict)


# --- helpers ---


def _est(e: Estimate) -> dict:
    return asdict(e)


def _grouped(r: q1.GroupedResult) -> dict:
    return {
        "effects": {k: _est(v) for k, v in r.effects.items()},
        "joint_test": asdict(r.joint_test) if r.joint_test else None,
        "trend": _est(r.trend) if r.trend else None,
    }


def _h2(r: q2.H2Result) -> dict:
    return {
        "delta": _est(r.delta),
        "delta_90": _est(r.delta_90),
        "tost_p_value": r.tost_p_value,
        "equivalent": r.equivalent,
        "bound_lp": r.bound,
        "states": {k: _est(v) for k, v in r.states.items()},
    }


def _h3(r: q3.H3Result) -> dict:
    d = {k: v for k, v in asdict(r).items() if k != "per_player"}
    return d


def restandardize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Recompute gold_diff_14_z within `by` (outcome-eligible games), its lag and the H1 sample.

    For the registered sensitivity run that standardizes within tier x role, ignoring patch.
    """
    d = df.sort_values(["player_key", "game_start_at", "match_key"]).copy()
    elig = d["outcome_eligible"].astype(bool) & d["gold_diff_14"].notna()
    grp = d.loc[elig].groupby(by)["gold_diff_14"]
    z = (d.loc[elig, "gold_diff_14"] - grp.transform("mean")) / grp.transform("std")
    d["gold_diff_14_z"] = np.nan
    d.loc[elig, "gold_diff_14_z"] = z
    played = ~d["remake"].astype(bool)
    d.loc[played, "prev_gold_diff_14_z"] = (
        d.loc[played].groupby("player_key")["gold_diff_14_z"].shift(1)
    )
    d["q1_eligible"] = elig & d["gold_diff_14_z"].notna() & d["lost_prev"].notna()
    return d


# --- the analysis ---


def run_all(
    inputs: Inputs, n_sims: int = q3.N_SIMULATIONS, n_boot: int = 10_000, seed: int = 20261118
) -> dict:
    pg = inputs.player_games.copy()
    out: dict = {"generated_at": datetime.now(UTC).isoformat(), "descriptive": {}}

    # Primary
    h1 = q1.fit_h1(pg)
    h2 = q2.fit_h2(inputs.team_focal)
    h3 = q3.fit_h3(q3.win_sequences(pg), seed=seed, n_sims=n_sims, n_boot=n_boot)
    reject, adjusted = holm([h1.p_value, h2.tost_p_value, h3.p_value])
    out["primary"] = {
        "H1": {**_est(h1), "holm_p": adjusted[0], "reject": bool(reject[0])},
        "H2": {**_h2(h2), "holm_p": adjusted[1], "equivalence_supported": bool(reject[1])},
        "H3": {**_h3(h3), "holm_p": adjusted[2], "reject_independence": bool(reject[2])},
    }

    # Secondary
    h1a, h1b, h1c = q1.fit_h1a(pg), q1.fit_h1b(pg), q1.fit_h1c(pg)
    autofill = inputs.team_focal.loc[
        inputs.team_focal["autofill_sample"].fillna(False).astype(bool)
    ]
    h2a = q2.fit_h2a(autofill)
    outcomes = {o: q1.fit_h1(pg, outcome=o) for o in q1.SECONDARY}
    cont = selection.fit_continuation(pg)
    family = {
        "H1a trend": h1a.trend.p_value,
        "H1b break interaction": h1b.joint_test.p_value,
        "H1c tier interaction": h1c.joint_test.p_value,
        "H2a autofill": h2a.p_value,
        **{f"H1 {o}": e.p_value for o, e in outcomes.items()},
        "continuation after loss": cont.loss_effect.p_value,
    }
    reject, adjusted = benjamini_hochberg(list(family.values()))
    out["secondary"] = {
        "bh": {
            k: {"p": p, "bh_p": a, "reject": bool(r)}
            for (k, p), a, r in zip(family.items(), adjusted, reject, strict=True)
        },
        "H1a": _grouped(h1a),
        "H1b": _grouped(h1b),
        "H1c": _grouped(h1c),
        "H2a": asdict(h2a),
        "H1 secondary outcomes": {o: _est(e) for o, e in outcomes.items()},
    }

    # Selection (5.1)
    pg["ipw"] = selection.ipw_weights(pg)
    out["selection"] = {
        "continuation": {
            "loss_effect": _est(cont.loss_effect),
            "stop_rate_after_loss": cont.stop_rate_after_loss,
            "stop_rate_after_win": cont.stop_rate_after_win,
        },
        "H1 IPW": _est(q1.fit_h1(pg, weights="ipw")),
        "bound": asdict(selection.selection_bound(h1, cont.stop_rate_after_loss)),
    }

    # Registered versions of the deviated analyses
    out["registered_versions"] = {
        "H1 (lag filled, Deviation 1)": _est(q1.fit_h1(pg, lag="fill")),
        "H3 (drift null, Deviation 2)": _h3(
            q3.fit_h3(q3.win_sequences(pg), seed=seed, n_sims=n_sims, n_boot=n_boot, null="drift")
        ),
    }

    # Sensitivity (section 8)
    duration = pg["duration_seconds"].fillna(0)
    sens: dict = {
        "H1 without lagged outcome": _est(q1.fit_h1(pg, lag="none")),
        "H1 games 15+ minutes": _est(q1.fit_h1(pg.loc[duration >= 15 * 60])),
        "H1 z within tier x role": _est(q1.fit_h1(restandardize(pg, ["sampled_tier", "role_key"]))),
        "H1 excluding likely duos": _est(q1.fit_h1(pg.loc[~pg["likely_duo"].astype(bool)])),
        "H2 without the 20 LP adjustment": _h2(
            q2.fit_h2(inputs.team_focal, outcome="strength_gap_unadjusted")
        ),
        "H2 with match result as covariate": _h2(
            q2.fit_h2(inputs.team_focal, controls=("won_match",))
        ),
        "H2 placebo (random non-focal player)": _h2(q2.fit_h2(inputs.team_placebo)),
        "H3 constant win rate (whole-sequence shuffle)": _h3(
            q3.fit_h3(
                q3.win_sequences(pg), seed=seed, n_sims=n_sims, n_boot=n_boot, block_size=None
            )
        ),
        "H3 50-game blocks": _h3(
            q3.fit_h3(q3.win_sequences(pg), seed=seed, n_sims=n_sims, n_boot=n_boot, block_size=50)
        ),
    }
    for gap, variant in sorted(inputs.session_variants.items()):
        sens[f"H1 session gap {gap} min"] = _est(q1.fit_h1(variant))
        sens[f"H1a session gap {gap} min"] = _grouped(q1.fit_h1a(variant))
    out["sensitivity"] = sens

    # Descriptive and game-terms translation
    elig = pg["outcome_eligible"].astype(bool)
    gold_sd = float(pg.loc[elig, "gold_diff_14"].std()) if "gold_diff_14" in pg else float("nan")
    cs_sd = float(pg.loc[elig, "cs_diff_14"].std()) if "cs_diff_14" in pg else float("nan")
    out["descriptive"] = {
        "players": int(pg["player_key"].nunique()),
        "player_games": int(len(pg)),
        "h1_sample": h1.n_obs,
        "q2_matches": int(len(inputs.team_focal)),
        "q2_autofill_sample": int(len(autofill)),
        "likely_duo_share": float(pg["likely_duo"].mean()),
        "gold_diff_14_sd": gold_sd,
        "cs_diff_14_sd": cs_sd,
        "H1 in gold at 14": h1.estimate * gold_sd,
        "H1 in CS at 14": h1.estimate * cs_sd,
    }
    out["_h3_per_player"] = h3.per_player
    return out


# --- report ---


def _fmt(x: float, nd: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def _row(name: str, e: dict) -> str:
    return (
        f"| {name} | {_fmt(e['estimate'])} | [{_fmt(e['ci_low'])}, {_fmt(e['ci_high'])}] "
        f"| {_fmt(e['p_value'], 4)} | {e['n_obs']} |"
    )


def _primary_row(name: str, e: dict, decision: str, nd: int = 3) -> str:
    """One row of the primary table; for H2 the p is the TOST p."""
    return (
        f"| {name} | {_fmt(e['estimate'], nd)} "
        f"| [{_fmt(e['ci_low'], nd)}, {_fmt(e['ci_high'], nd)}] "
        f"| {_fmt(e['p_value'], 4)} | {_fmt(e['holm_p'], 4)} | {decision} |"
    )


def write_report(results: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    per_player = results.pop("_h3_per_player")
    per_player.to_csv(out_dir / "h3_per_player.csv", index=False)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=float))

    p, d = results["primary"], results["descriptive"]
    cont = results["selection"]["continuation"]
    h1_decision = "effect" if p["H1"]["reject"] else "no detectable effect"
    h2_decision = (
        "equivalent within ±25 LP" if p["H2"]["equivalence_supported"] else "equivalence not shown"
    )
    if not p["H3"]["reject_independence"]:
        h3_decision = "consistent with independent games"
    else:
        h3_decision = (
            "streakier than chance" if p["H3"]["mean_z"] < 0 else "less streaky than chance"
        )
    lines = [
        "# Ekko results",
        "",
        f"Generated {results['generated_at']} by `python -m ekko_analysis.run`. Definitions and "
        "decision rules: `analysis/PREREGISTRATION.md` (with Deviations 1 and 2).",
        "",
        f"{d['players']} players, {d['player_games']} player-games, {d['h1_sample']} in the H1 "
        f"sample, {d['q2_matches']} Q2 matches ({d['q2_autofill_sample']} in the autofill sample).",
        "",
        "## Primary hypotheses (Holm across H1, H2, H3)",
        "",
        "| Hypothesis | Estimate | 95% CI | p | Holm p | Decision |",
        "|---|---|---|---|---|---|",
        _primary_row("H1 tilt: loss → gold diff at 14 (SD)", p["H1"], h1_decision),
        _primary_row(
            "H2 loser's queue: Δ gap W3+ − L3+ (LP)",
            {**p["H2"]["delta"], "holm_p": p["H2"]["holm_p"], "p_value": p["H2"]["tost_p_value"]},
            h2_decision,
            nd=1,
        ),
        _primary_row(
            "H3 streaks: mean runs z", {"estimate": p["H3"]["mean_z"], **p["H3"]}, h3_decision
        ),
        "",
        "H2's p is the equivalence (TOST) p: small means the gap difference is shown to lie within "
        "±25 LP. Its interval is the 95% CI; the equivalence decision uses the 90% CI.",
        "",
        f"In game terms, H1 is about {_fmt(d['H1 in gold at 14'], 0)} gold and "
        f"{_fmt(d['H1 in CS at 14'], 1)} CS at 14 minutes (approximate: estimate × overall SD).",
        "",
        "## Secondary (Benjamini–Hochberg, q = 0.05)",
        "",
        "| Test | p | BH p | Reject |",
        "|---|---|---|---|",
        *[
            f"| {k} | {_fmt(v['p'], 4)} | {_fmt(v['bh_p'], 4)} | {'yes' if v['reject'] else 'no'} |"
            for k, v in results["secondary"]["bh"].items()
        ],
        "",
        "## Selection (5.1)",
        "",
        f"Stop rate after a loss {_fmt(cont['stop_rate_after_loss'])}, "
        f"after a win {_fmt(cont['stop_rate_after_win'])}. "
        f"{results['selection']['bound']['explanation']}",
        "",
        "| Model | Estimate | 95% CI | p | n |",
        "|---|---|---|---|---|",
        _row("H1 (primary)", p["H1"]),
        _row("H1 inverse probability weighted", results["selection"]["H1 IPW"]),
        _row(
            "H1 registered version (lag filled)",
            results["registered_versions"]["H1 (lag filled, Deviation 1)"],
        ),
        "",
        "## Sensitivity (section 8)",
        "",
        "| Run | Estimate | 95% CI | p | n |",
        "|---|---|---|---|---|",
        *[_row(k, v) for k, v in results["sensitivity"].items() if "estimate" in v],
        *[_row(k, v["delta"]) for k, v in results["sensitivity"].items() if "delta" in v],
        "",
        "H3 variants (mean runs z, 95% CI):",
        "",
        *[
            f"- {k}: {_fmt(v['mean_z'])} [{_fmt(v['ci_low'])}, {_fmt(v['ci_high'])}]"
            for k, v in {**results["sensitivity"], **results["registered_versions"]}.items()
            if "mean_z" in v
        ],
        "",
    ]
    (out_dir / "results.md").write_text("\n".join(lines))
    _figure(results, out_dir / "h1_by_group.png")


def _figure(results: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = [
        ("Losses in a row (H1a)", results["secondary"]["H1a"]["effects"]),
        ("Break before the game (H1b)", results["secondary"]["H1b"]["effects"]),
        ("Tier group (H1c)", results["secondary"]["H1c"]["effects"]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True)
    for ax, (title, effects) in zip(axes, groups, strict=True):
        labels = list(effects)
        est = [effects[k]["estimate"] for k in labels]
        err = [
            [e - effects[k]["ci_low"] for k, e in zip(labels, est, strict=True)],
            [effects[k]["ci_high"] - e for k, e in zip(labels, est, strict=True)],
        ]
        ax.errorbar(range(len(labels)), est, yerr=err, fmt="o", color="#1b2538", capsize=3)
        ax.axhline(0, color="#8a96a8", lw=0.8)
        ax.set_xticks(range(len(labels)), labels, rotation=20)
        ax.set_title(title, fontsize=10)
    axes[0].set_ylabel("Effect of a loss on gold diff at 14 (SD)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- entry point ---


def check_phase1(path: Path) -> int:
    """Number of focal players, or SystemExit if this isn't a Phase 1 build."""
    with duckdb.connect(str(path), read_only=True) as con:
        tables = {
            r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()
        }
        if "fct_match_team_strength" not in tables:
            raise SystemExit(
                "No Q2 mart: build dbt with --vars '{phase: 1}' on the Phase 1 crawl first."
            )
        return con.execute(
            "select count(distinct player_key) from main.fct_player_games"
        ).fetchall()[0][0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--session-warehouse", action="append", default=[], metavar="GAP=PATH")
    parser.add_argument("--allow-small", action="store_true")
    args = parser.parse_args(argv)
    warnings.simplefilter("ignore")

    path = warehouse_path()
    players = check_phase1(path)
    if players < MIN_PLAYERS:
        if not args.allow_small:
            raise SystemExit(
                f"Only {players} players: not the full Phase 1 crawl. Refusing to run."
            )
        if args.out.resolve() == DEFAULT_OUT.resolve():
            raise SystemExit("--allow-small output must go outside analysis/results.")
    variants = {}
    for spec in args.session_warehouse:
        gap, p = spec.split("=", 1)
        variants[int(gap)] = load_player_games(Path(p))
    inputs = Inputs(
        load_player_games(path),
        load_team_strength("focal", path),
        load_team_strength("placebo", path),
        variants,
    )
    write_report(run_all(inputs), args.out)
    print(f"wrote {args.out}/results.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
