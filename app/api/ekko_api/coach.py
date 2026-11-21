"""AI coach (PROJECT_PLAN.md section 9): a short written summary of a report, checked before it's shown.

1. `facts(report)` turns the report into a flat sheet of facts with IDs, already rounded the way the
   page shows them. The model sees only this sheet, never match data, so it can't compute numbers.
2. The model (Claude, structured output) writes a summary, 2-3 findings that cite fact IDs, and 0-2
   recommendations chosen from APPROVED_ACTIONS.
3. `verify(output, facts)` runs on every response:
   - every number in the text must equal a fact value;
   - cited fact IDs must exist;
   - no effect may be claimed for a finding whose facts aren't supported;
   - each recommendation needs its supporting finding;
   - nothing may be claimed about the matchmaker.
4. A response that fails is regenerated once with the violations listed; if it still fails, a
   deterministic template is used instead. `source` says which one the reader got.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"
MAX_ATTEMPTS = 2

APPROVED_ACTIONS = {
    # action: the facts that must be supported for it to be recommended
    "take_a_break_after_a_loss": ("cooldown.supported", "tilt.supported"),  # either one
    "stop_after_losses_in_a_row": ("stop_rule.supported",),
    "keep_playing_as_usual": (),  # always allowed
}
Action = Literal["take_a_break_after_a_loss", "stop_after_losses_in_a_row", "keep_playing_as_usual"]

# Words that assert an effect. In a finding about an unsupported block they must come with a hedge.
CLAIM_WORDS = re.compile(
    r"\b(tilt(?:s|ed|ing)?|worse|better|drops?|dropped|falls? behind|ahead|behind|hurts?|helps?|"
    r"stronger|weaker|stack(?:ed)?|rigged|loser'?s queue|should stop)\b",
    re.IGNORECASE,
)
HEDGES = re.compile(
    r"\b(no clear|no reliable|not clear|isn'?t clear|not enough|can'?t (?:tell|say)|"
    r"no (?:sign|evidence)|doesn'?t show|didn'?t show|too few|within the range of chance)\b",
    re.IGNORECASE,
)
MATCHMAKER_CLAIM = re.compile(
    r"\b(rigged|loser'?s queue|matchmak\w* (?:is|was) (?:unfair|against))\b", re.IGNORECASE
)
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")


# --- facts ---


def _r(x: float | None, nd: int = 0):
    if x is None:
        return None
    v = round(x, nd)
    return int(v) if nd == 0 else v


def facts(report: dict) -> dict:
    """The fact sheet the model sees. Values are rounded exactly as the page shows them."""
    t, c, s, m = report["tilt"], report["cooldown"], report["stop_rule"], report["matchmaking"]
    g = t.get("gold_per_sd") or 0
    f: dict = {
        "games.analyzed": report["games_analyzed"],
        "rank.tier": report["rank"]["tier"],
        "priors.placeholder": report["priors_are_placeholders"],
        "minute_mark": 14,
        "tilt.supported": bool(t["supported"]),
        "tilt.enough_data": t["shrunk"] is not None,
    }
    if t["shrunk"]:
        f |= {
            "tilt.games_used": t["games_used"],
            "tilt.gold_after_loss": _r(t["shrunk"]["estimate"] * g),
            "tilt.gold_low": _r(t["shrunk"]["low"] * g),
            "tilt.gold_high": _r(t["shrunk"]["high"] * g),
        }
    f["cooldown.supported"] = bool(c["supported"])
    for name in ("quick_requeue", "after_a_break"):
        iv = c.get(name)
        if iv:
            f[f"cooldown.{name}.gold"] = _r(iv["estimate"] * g)
            f[f"cooldown.{name}.games"] = iv["n"]
    f |= {
        "stop_rule.supported": bool(s["supported"]),
        "stop_rule.after_losses": s["after_losses_in_a_row"],
        "stop_rule.games": s["games"],
        "stop_rule.overall_win_pct": _r(100 * s["overall_win_rate"])
        if s["overall_win_rate"] == s["overall_win_rate"]
        else None,
    }
    if s["win_rate"] is not None and s["games"] >= 10:
        f["stop_rule.win_pct"] = _r(100 * s["win_rate"])
        f["stop_rule.win_pct_low"] = _r(100 * s["low"])
        f["stop_rule.win_pct_high"] = _r(100 * s["high"])
    f["matchmaking.games"] = m["games"]
    if m.get("mean_gap_lp") is not None:
        f["matchmaking.mean_gap_lp"] = _r(m["mean_gap_lp"])
    return {k: v for k, v in f.items() if v is not None}


def _block(fact_id: str) -> str:
    return fact_id.split(".")[0]


# --- model output ---


class Finding(BaseModel):
    text: str = Field(description="One or two plain sentences addressed to the player.")
    fact_ids: list[str] = Field(description="IDs from the fact sheet this finding is based on.")


class Recommendation(BaseModel):
    action: Action
    text: str = Field(description="One sentence telling the player what to do and why.")
    fact_ids: list[str]


class CoachOutput(BaseModel):
    summary: str = Field(description="Two or three sentences.")
    findings: list[Finding]
    recommendations: list[Recommendation]


# --- verification ---


@dataclass
class Verdict:
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def _allowed_numbers(fs: dict) -> set[float]:
    allowed = set()
    for v in fs.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        allowed |= {float(v), float(abs(v))}
    return allowed


def verify(out: CoachOutput, fs: dict) -> Verdict:
    v = Verdict()
    allowed = _allowed_numbers(fs)
    texts = [("summary", out.summary, [])]
    texts += [(f"finding {i + 1}", f.text, f.fact_ids) for i, f in enumerate(out.findings)]
    texts += [
        (f"recommendation {i + 1}", r.text, r.fact_ids) for i, r in enumerate(out.recommendations)
    ]

    if not 2 <= len(out.findings) <= 3:
        v.violations.append(f"needs 2-3 findings, got {len(out.findings)}")
    if len(out.recommendations) > 2:
        v.violations.append(f"at most 2 recommendations, got {len(out.recommendations)}")

    for where, text, ids in texts:
        for n in _numbers(text):
            value = float(n.rstrip("%").replace(",", ""))
            if value not in allowed:
                v.violations.append(f"{where}: the number {n} isn't in the facts")
        for fid in ids:
            if fid not in fs:
                v.violations.append(f"{where}: cites unknown fact {fid}")
        if MATCHMAKER_CLAIM.search(text) and not HEDGES.search(text):
            v.violations.append(f"{where}: claims something about the matchmaker")

    for i, f in enumerate(out.findings):
        blocks = {_block(fid) for fid in f.fact_ids if fid in fs}
        unsupported = [b for b in blocks if fs.get(f"{b}.supported") is False]
        if unsupported and CLAIM_WORDS.search(f.text) and not HEDGES.search(f.text):
            v.violations.append(
                f"finding {i + 1}: claims an effect but {', '.join(sorted(unsupported))} isn't supported"
            )

    for i, r in enumerate(out.recommendations):
        needs = APPROVED_ACTIONS[r.action]
        if needs and not any(fs.get(n) for n in needs):
            v.violations.append(f"recommendation {i + 1}: '{r.action}' needs {' or '.join(needs)}")
    if not out.summary.strip():
        v.violations.append("summary is empty")
    if not HEDGES.search(out.summary) and CLAIM_WORDS.search(out.summary):
        claimed = {b for b in ("tilt", "cooldown", "stop_rule") if fs.get(f"{b}.supported")}
        if not claimed:
            v.violations.append("summary claims an effect but no finding is supported")
    return v


# --- template fallback ---


def template(fs: dict) -> CoachOutput:
    """Deterministic text that passes `verify` by construction."""
    findings, recs = [], []
    if fs.get("tilt.supported") and fs["tilt.gold_after_loss"] < 0:
        findings.append(
            Finding(
                text=f"After a loss you start your next game about {abs(fs['tilt.gold_after_loss'])} gold "
                f"behind your usual at minute {fs['minute_mark']}.",
                fact_ids=["tilt.gold_after_loss", "tilt.supported"],
            )
        )
    elif fs.get("tilt.supported"):
        findings.append(
            Finding(
                text=f"After a loss you start your next game about {fs['tilt.gold_after_loss']} gold "
                f"ahead of your usual at minute {fs['minute_mark']}.",
                fact_ids=["tilt.gold_after_loss", "tilt.supported"],
            )
        )
    elif fs.get("tilt.enough_data"):
        findings.append(
            Finding(
                text="Losing a game shows no clear effect on how your next game starts.",
                fact_ids=["tilt.supported"],
            )
        )
    else:
        findings.append(
            Finding(
                text="There's not enough back-to-back play yet to judge tilt.",
                fact_ids=["tilt.enough_data"],
            )
        )
    if fs.get("stop_rule.supported"):
        findings.append(
            Finding(
                text=f"After {fs['stop_rule.after_losses']} losses in a row you won {fs['stop_rule.win_pct']}% "
                f"of the next games, against {fs['stop_rule.overall_win_pct']}% overall.",
                fact_ids=["stop_rule.win_pct", "stop_rule.overall_win_pct", "stop_rule.supported"],
            )
        )
        recs.append(
            Recommendation(
                action="stop_after_losses_in_a_row",
                text=f"Consider ending the session after {fs['stop_rule.after_losses']} losses in a row.",
                fact_ids=["stop_rule.supported"],
            )
        )
    else:
        findings.append(
            Finding(
                text="Losing streaks show no clear effect on your next game's result.",
                fact_ids=["stop_rule.supported"],
            )
        )
    if fs.get("cooldown.supported"):
        recs.append(
            Recommendation(
                action="take_a_break_after_a_loss",
                text="After a loss, take a short break before queueing again.",
                fact_ids=["cooldown.supported"],
            )
        )
    if not recs:
        recs.append(
            Recommendation(
                action="keep_playing_as_usual",
                text="Nothing in these games says you need to change how you queue.",
                fact_ids=[],
            )
        )
    summary = f"This report covers {fs['games.analyzed']} ranked games. " + (
        "One pattern stands out; the details are below."
        if any(fs.get(f"{b}.supported") for b in ("tilt", "stop_rule", "cooldown"))
        else "No clear pattern stands out, which is common with this many games."
    )
    return CoachOutput(summary=summary, findings=findings[:3], recommendations=recs[:2])


# --- generation ---

SYSTEM = """You write a short coaching note for a League of Legends player from their personal report.

You get a fact sheet (JSON) and nothing else. Rules:
- Use only numbers that appear in the fact sheet, written exactly as given (rounded integers; percentages with a % sign). Don't compute new numbers, ranges or differences.
- Every finding lists the fact IDs it relies on.
- A block whose `<block>.supported` is false shows no reliable effect. Say so plainly ("no clear effect"); never describe it as an effect, a trend or "a slight" anything.
- Never say anything about whether matchmaking is fair; one player's games can't show that.
- Recommendations: choose only from the allowed actions, and only when their evidence is supported. If nothing is supported, recommend keep_playing_as_usual.
- Plain, warm, direct. Address the player as "you". No jargon (no "standard deviation", "interval", "shrinkage")."""


def _prompt(fs: dict, violations: list[str] | None) -> str:
    body = "Fact sheet:\n" + json.dumps(fs, indent=1, sort_keys=True)
    body += "\n\nAllowed actions: " + ", ".join(APPROVED_ACTIONS)
    if violations:
        body += (
            "\n\nYour previous note was rejected by the checker:\n- "
            + "\n- ".join(violations)
            + "\nWrite it again without these problems."
        )
    return body


@dataclass
class CoachResult:
    output: CoachOutput
    source: Literal["model", "template"]
    attempts: int
    violations: list[list[str]]  # per model attempt


def coach(report: dict, client=None, model: str = MODEL) -> CoachResult:
    """Model note if it passes verification within MAX_ATTEMPTS, else the template.

    `client` is an Anthropic client (or a test double with the same `beta.messages.parse`); with no
    client, the template is used directly.
    """
    fs = facts(report)
    history: list[list[str]] = []
    if client is not None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            out = _generate(client, model, fs, history[-1] if history else None)
            if out is None:
                history.append(["no usable response (refusal or truncated)"])
                continue
            verdict = verify(out, fs)
            if verdict.ok:
                return CoachResult(out, "model", attempt, history)
            history.append(verdict.violations)
    return CoachResult(template(fs), "template", len(history), history)


def _generate(client, model: str, fs: dict, violations: list[str] | None) -> CoachOutput | None:
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # a safety decline is retried on a fallback model in the same call
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(fs, violations)}],
        output_format=CoachOutput,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    return response.parsed_output
