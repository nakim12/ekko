"""Coach evaluation (PROJECT_PLAN.md 9.2): rule-based metrics, with and without the verification layer.

    python -m ekko_api.coach_eval --yes [--n 50] [--out data/coach_eval.json]

Profiles are synthetic edge cases: tiny samples, intervals crossing zero, extreme values and
contradictory signals. The plan's 100 real profiles come from the Phase 1 data, later. Each profile is
run twice:
- "verified": `coach.coach`, i.e. verification, one retry, then template fallback. This is what users see.
- "unverified": one model call, shown as is.

Metrics (computed exactly on what the reader would see):
- numeric_accuracy: share of numbers in the text that match a fact.
- unsupported_claim_rate: share of findings that assert an effect for a block that isn't supported.
- coverage: share of supported blocks that some finding cites.
- template_rate (verified only): how often the model note was replaced.

Caveat: unsupported claims are detected with the same word rules the verifier uses, so the verified
arm scores ~0 by construction. The informative number is the unverified arm's rate (how often the
model alone would have misled), plus the LLM-judge pass the plan adds later (clarity, tone and
appropriate certainty, calibrated against hand grades with Cohen's kappa).

Costs money: about 2-3 model calls per profile (verified arm: 1-2, unverified arm: 1).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from . import coach

BLOCKS = ("tilt", "cooldown", "stop_rule")


def profiles(n: int = 50, seed: int = 0) -> list[dict]:
    """Synthetic reports covering the edge cases, deterministic for a seed."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        kind = i % 5
        tiny = kind == 0
        crossing = kind == 1
        extreme = kind == 2
        contradictory = kind == 3

        def iv(center, half):
            return {
                "estimate": center,
                "low": center - half,
                "high": center + half,
                "n": rng.randint(15, 80),
            }

        if tiny:
            tilt_iv, tilt_ok = None, False
        elif crossing:
            tilt_iv, tilt_ok = iv(rng.uniform(-0.1, 0.1), 0.25), False
        elif extreme:
            tilt_iv, tilt_ok = iv(rng.choice([-1.1, 0.9]), 0.2), True
        elif contradictory:
            tilt_iv, tilt_ok = iv(0.3, 0.12), True  # better after a loss...
        else:
            tilt_iv, tilt_ok = iv(-0.25, 0.1), True
        stop_ok = contradictory or (kind == 4 and rng.random() < 0.5)  # ...but streaks hurt
        stop_games = rng.randint(0, 9) if tiny else rng.randint(10, 40)
        win = rng.uniform(0.15, 0.35) if stop_ok else rng.uniform(0.4, 0.6)
        out.append(
            {
                "games_analyzed": rng.randint(20, 100) if tiny else rng.randint(80, 100),
                "rank": {
                    "tier": rng.choice(["IRON", "GOLD", "DIAMOND", "MASTER"]),
                    "division": "II",
                    "league_points": 50,
                },
                "priors_are_placeholders": True,
                "tilt": {
                    "games_used": 0 if tiny else rng.randint(30, 70),
                    "gold_per_sd": 1428.0,
                    "shrunk": tilt_iv,
                    "supported": tilt_ok,
                },
                "cooldown": {
                    "quick_requeue": None if tiny else iv(-0.3 if kind == 4 else 0.0, 0.2),
                    "after_a_break": None if tiny else iv(0.0, 0.2),
                    "supported": kind == 4 and not tiny,
                },
                "stop_rule": {
                    "after_losses_in_a_row": 2,
                    "games": stop_games,
                    "win_rate": win if stop_games else None,
                    "low": max(0.0, win - 0.15),
                    "high": min(1.0, win + 0.15) if not stop_ok else min(win + 0.12, 0.5),
                    "overall_win_rate": rng.uniform(0.48, 0.6),
                    "supported": stop_ok and stop_games >= 10,
                },
                "matchmaking": {
                    "games": 10,
                    "mean_gap_lp": rng.uniform(-80, 80),
                    "low": -150,
                    "high": 150,
                    "supported": False,
                },
            }
        )
    return out


def score(out: coach.CoachOutput, fs: dict) -> dict:
    allowed = coach._allowed_numbers(fs)
    texts = [out.summary, *(f.text for f in out.findings), *(r.text for r in out.recommendations)]
    numbers = [n for t in texts for n in coach._numbers(t)]
    correct = sum(float(n.rstrip("%").replace(",", "")) in allowed for n in numbers)
    unsupported = 0
    for f in out.findings:
        blocks = {coach._block(fid) for fid in f.fact_ids if fid in fs}
        if (
            any(fs.get(f"{b}.supported") is False for b in blocks)
            and coach.CLAIM_WORDS.search(f.text)
            and not coach.HEDGES.search(f.text)
        ):
            unsupported += 1
    supported = [b for b in BLOCKS if fs.get(f"{b}.supported")]
    cited = {coach._block(fid) for f in out.findings for fid in f.fact_ids}
    return {
        "numbers": len(numbers),
        "numbers_correct": correct,
        "findings": len(out.findings),
        "unsupported_findings": unsupported,
        "supported_blocks": len(supported),
        "supported_blocks_cited": sum(b in cited for b in supported),
    }


def _aggregate(rows: list[dict]) -> dict:
    tot = {k: sum(r[k] for r in rows) for k in rows[0]} if rows else {}
    div = lambda a, b: a / b if b else None  # noqa: E731
    return {
        "profiles": len(rows),
        "numeric_accuracy": div(tot.get("numbers_correct", 0), tot.get("numbers", 0)),
        "unsupported_claim_rate": div(tot.get("unsupported_findings", 0), tot.get("findings", 0)),
        "coverage": div(tot.get("supported_blocks_cited", 0), tot.get("supported_blocks", 0)),
    }


def evaluate(client, n: int = 50, seed: int = 0) -> dict:
    verified, unverified, sources = [], [], []
    for report in profiles(n, seed):
        fs = coach.facts(report)
        result = coach.coach(report, client)
        verified.append(score(result.output, fs))
        sources.append(result.source)
        raw = coach._generate(client, coach.MODEL, fs, None)
        if raw is not None:
            unverified.append(score(raw, fs))
    return {
        "model": coach.MODEL,
        "verified": {
            **_aggregate(verified),
            "template_rate": sources.count("template") / len(sources),
        },
        "unverified": _aggregate(unverified),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the coach (costs money; needs ANTHROPIC_API_KEY)."
    )
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("data/coach_eval.json"))
    parser.add_argument(
        "--yes", action="store_true", help="confirm the spend (about 2-3 model calls per profile)"
    )
    args = parser.parse_args(argv)
    if not args.yes:
        print(
            f"This makes about {2 * args.n}-{3 * args.n} calls to {coach.MODEL}. Rerun with --yes to proceed."
        )
        return 1
    import anthropic
    from dotenv import load_dotenv

    load_dotenv()
    result = evaluate(anthropic.Anthropic(), args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
